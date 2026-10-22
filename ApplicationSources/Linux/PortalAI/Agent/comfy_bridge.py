from __future__ import annotations
from pathlib import Path
import json, time, uuid, shutil, urllib.parse, urllib.request
from _common import load_config, resolve_root, http_json, multipart_upload, root_dir
from runtime_policy import require_space, portable_path
from media_paths import media_reference, media_output

class ComfyBridge:
    def __init__(self):
        self.cfg = load_config()
        self.ccfg = self.cfg["comfy"]
        self.base = self.ccfg["base_url"].rstrip("/")

    def health(self):
        # /system_stats is a simple ComfyUI reachability check.
        return http_json("GET", self.base + "/system_stats", timeout=10)

    def interrupt(self):
        """Interrupt ComfyUI's currently executing workflow."""
        req = urllib.request.Request(self.base + "/interrupt", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return {"interrupted": True}

    def workflow(self, key: str) -> dict:
        key = key.replace('_uncensored', '_official')
        fname = self.ccfg["workflows"][key]
        path = resolve_root(self.ccfg["workflows_dir"]) / fname
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def upload_image(self, path: Path) -> str:
        path = media_reference(root_dir(), path)
        if not path.exists():
            raise FileNotFoundError(path)
        # ComfyUI returns a name/subfolder/type object. Use returned name in LoadImage.
        require_space(root_dir(), path.stat().st_size, for_outputs=True)
        resp = multipart_upload(
            self.base + "/upload/image",
            path,
            "image",
            {"type": "input", "overwrite": "true"}
        )
        name = resp.get("name")
        sub = resp.get("subfolder", "")
        if not name:
            raise RuntimeError(f"Unexpected ComfyUI upload response: {resp}")
        return f"{sub}/{name}".strip("/")

    def workflow_file(self, relative_path: str | Path) -> dict:
        """Load an API-format workflow by PortableAI-relative path."""
        from academic_policy import blocked_name, NOTICE
        if blocked_name(relative_path): raise ValueError(NOTICE)
        path = resolve_root(relative_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise RuntimeError(f"Workflow is not a JSON object: {path}")
        return data

    def _input_dir(self) -> Path:
        """Input and output can be configured independently by the service."""
        out = resolve_root(self.ccfg["output_dir"]).resolve()
        input_dir = resolve_root(self.ccfg['input_dir']).resolve() if self.ccfg.get('input_dir') else out.parent / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        return input_dir

    def stage_input_file(self, path: Path, prefix: str = "portableai") -> tuple[str, Path]:
        """Copy a local file into ComfyUI/input and return (Comfy name, staged path)."""
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in path.name)
        name = f"{prefix}_{uuid.uuid4().hex[:10]}_{safe}"
        dst = self._input_dir() / name
        require_space(root_dir(), path.stat().st_size, for_outputs=True)
        shutil.copy2(path, dst)
        return name, dst

    @staticmethod
    def cleanup_staged_file(path: Path | str | None) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _nodes_by_type(wf, class_type):
        return [(nid, node) for nid, node in wf.items() if isinstance(node, dict) and node.get("class_type") == class_type]

    def configure_t2i(self, wf, prompt, negative=None, width=None, height=None, seed=None):
        text_nodes = self._nodes_by_type(wf, "CLIPTextEncode")
        # API workflow has positive first, negative second.
        if not text_nodes:
            raise RuntimeError("No CLIPTextEncode node found")
        pos_id, pos = text_nodes[0]
        pos["inputs"]["text"] = prompt
        if negative is not None and len(text_nodes) > 1:
            text_nodes[1][1]["inputs"]["text"] = negative

        latent_nodes = self._nodes_by_type(wf, "EmptySD3LatentImage") or self._nodes_by_type(wf, "EmptyLatentImage")
        if latent_nodes:
            latent = latent_nodes[0][1]["inputs"]
            if width: latent["width"] = int(width)
            if height: latent["height"] = int(height)

        samplers = self._nodes_by_type(wf, "KSampler")
        if samplers and seed is not None:
            samplers[0][1]["inputs"]["seed"] = int(seed)
        return wf

    def configure_edit(self, wf, image_name, instruction, seed=None):
        loads = self._nodes_by_type(wf, "LoadImage")
        if not loads:
            raise RuntimeError("No LoadImage node found")
        # Node 76 is the active single-reference image in the supplied workflow.
        target = wf.get("76")
        if not (isinstance(target, dict) and target.get("class_type") == "LoadImage"):
            target = loads[0][1]
        target["inputs"]["image"] = image_name

        texts = self._nodes_by_type(wf, "CLIPTextEncode")
        pos = None
        for _, node in texts:
            title = (node.get("_meta") or {}).get("title", "").lower()
            if "positive" in title:
                pos = node
                break
        if pos is None and texts:
            pos = texts[0][1]
        if pos is None:
            raise RuntimeError("No positive CLIPTextEncode node found")
        pos["inputs"]["text"] = instruction

        if seed is not None:
            noises = self._nodes_by_type(wf, "RandomNoise")
            if noises:
                noises[0][1]["inputs"]["noise_seed"] = int(seed)
        return wf

    def configure_mask(self, wf, image_name, object_prompt, threshold=0.30, expand=8):
        source = wf.get("1")
        if not (isinstance(source, dict) and source.get("class_type") == "LoadImage"):
            loads = self._nodes_by_type(wf, "LoadImage")
            if not loads:
                raise RuntimeError("No LoadImage node found in object-mask workflow")
            source = loads[0][1]
        source["inputs"]["image"] = image_name

        segment = wf.get("4")
        if not isinstance(segment, dict):
            nodes = self._nodes_by_type(wf, "GroundingDinoSAM2Segment (segment anything2)")
            if not nodes:
                raise RuntimeError(
                    "Semantic object masking is not installed. Run Install_ObjectMasking.bat, "
                    "restart ComfyUI, then retry."
                )
            segment = nodes[0][1]
        segment["inputs"]["prompt"] = object_prompt
        segment["inputs"]["threshold"] = float(threshold)

        grow = wf.get("5")
        if isinstance(grow, dict) and grow.get("class_type") == "GrowMask":
            grow["inputs"]["expand"] = int(expand)
        return wf

    def configure_inpaint(self, wf, source_name, mask_name, instruction, seed=None, expand=None):
        # v14 inpaint workflows use node 1=source, node 2=mask, node 8=positive prompt,
        # node 17=RandomNoise. Fall back to type-based discovery where practical.
        src = wf.get("1")
        mask = wf.get("2")
        if not (isinstance(src, dict) and src.get("class_type") == "LoadImage"):
            loads = self._nodes_by_type(wf, "LoadImage")
            if len(loads) < 2:
                raise RuntimeError("Inpaint workflow must contain source and mask LoadImage nodes")
            src = loads[0][1]
            mask = loads[1][1]
        src["inputs"]["image"] = source_name
        mask["inputs"]["image"] = mask_name

        pos = wf.get("8")
        if not (isinstance(pos, dict) and pos.get("class_type") == "CLIPTextEncode"):
            texts = self._nodes_by_type(wf, "CLIPTextEncode")
            if not texts:
                raise RuntimeError("No CLIPTextEncode node found in inpaint workflow")
            pos = texts[0][1]
        pos["inputs"]["text"] = instruction

        if seed is not None:
            noise = wf.get("17")
            if isinstance(noise, dict) and noise.get("class_type") == "RandomNoise":
                noise["inputs"]["noise_seed"] = int(seed)
            else:
                noises = self._nodes_by_type(wf, "RandomNoise")
                if noises:
                    noises[0][1]["inputs"]["noise_seed"] = int(seed)

        if expand is not None:
            grows = self._nodes_by_type(wf, "GrowMask")
            if grows:
                grows[0][1]["inputs"]["expand"] = int(expand)
        return wf

    def configure_video(self, wf, image_name, prompt, seed=None, width=None, height=None, length=None, fps=None):
        loads = self._nodes_by_type(wf, "LoadImage")
        if not loads:
            raise RuntimeError("No LoadImage node found")
        loads[0][1]["inputs"]["image"] = image_name

        texts = self._nodes_by_type(wf, "CLIPTextEncode")
        positive = None
        for _, node in texts:
            title = (node.get("_meta") or {}).get("title", "").lower()
            if "positive" in title:
                positive = node
                break
        if positive is None and texts:
            positive = texts[0][1]
        if positive is None:
            raise RuntimeError("No positive prompt node found")
        positive["inputs"]["text"] = prompt

        wan = self._nodes_by_type(wf, "WanImageToVideo")
        if wan:
            inputs = wan[0][1]["inputs"]
            if width: inputs["width"] = int(width)
            if height: inputs["height"] = int(height)
            if length: inputs["length"] = int(length)

        if seed is not None:
            samplers = self._nodes_by_type(wf, "KSamplerAdvanced")
            for _, s in samplers:
                if s["inputs"].get("add_noise") == "enable":
                    s["inputs"]["noise_seed"] = int(seed)
                    break

        if fps is not None:
            vids = self._nodes_by_type(wf, "CreateVideo")
            if vids:
                vids[0][1]["inputs"]["fps"] = int(fps)
        return wf

    def configure_vace_video_edit(
        self,
        wf,
        video_name,
        prompt,
        negative=None,
        seed=None,
        width=832,
        height=480,
        length=81,
        fps=16,
        strength=1.0,
        lora_strength=0.30,
        fast=True,
        reference_image_name=None,
    ):
        """Configure the native ComfyUI Wan2.1 VACE 14B V2V API workflow."""
        loads = self._nodes_by_type(wf, "LoadVideo")
        if not loads:
            raise RuntimeError(
                "Wan VACE video-edit workflow requires the native ComfyUI LoadVideo node. "
                "Update ComfyUI if this node is unavailable."
            )
        loads[0][1]["inputs"]["file"] = video_name

        texts = self._nodes_by_type(wf, "CLIPTextEncode")
        positive = None
        negative_node = None
        for _, node in texts:
            title = (node.get("_meta") or {}).get("title", "").lower()
            if "positive" in title:
                positive = node
            elif "negative" in title:
                negative_node = node
        if positive is None and texts:
            positive = texts[0][1]
        if negative_node is None and len(texts) > 1:
            negative_node = texts[1][1]
        if positive is None or negative_node is None:
            raise RuntimeError("VACE workflow is missing positive/negative CLIPTextEncode nodes")
        positive["inputs"]["text"] = prompt
        if negative is not None:
            negative_node["inputs"]["text"] = negative

        vaces = self._nodes_by_type(wf, "WanVaceToVideo")
        if not vaces:
            raise RuntimeError(
                "WanVaceToVideo is unavailable. Update ComfyUI to a build with native Wan VACE support."
            )
        vace_id, vace = vaces[0]
        vi = vace["inputs"]
        vi["width"] = int(width)
        vi["height"] = int(height)
        vi["length"] = int(length)
        vi["batch_size"] = 1
        vi["strength"] = float(strength)

        # Optional continuity/style reference. The base workflow deliberately omits
        # it so ordinary V2V has trim_latent=0.
        wf.pop("16", None)
        vi.pop("reference_image", None)
        if reference_image_name:
            wf["16"] = {
                "inputs": {"image": reference_image_name},
                "class_type": "LoadImage",
                "_meta": {"title": "PortableAI VACE Reference Image"},
            }
            vi["reference_image"] = ["16", 0]

        unets = self._nodes_by_type(wf, "UNETLoader")
        clips = self._nodes_by_type(wf, "CLIPLoader")
        samplings = self._nodes_by_type(wf, "ModelSamplingSD3")
        samplers = self._nodes_by_type(wf, "KSampler")
        loras = self._nodes_by_type(wf, "LoraLoader")
        if not (unets and clips and samplings and samplers):
            raise RuntimeError("VACE workflow is missing required model/sampler nodes")

        unet_id, _ = unets[0]
        clip_id, _ = clips[0]
        sampling = samplings[0][1]
        sampler = samplers[0][1]

        if fast:
            if not loras:
                raise RuntimeError("Fast VACE mode requires the CausVid LoraLoader node")
            lora_id, lora = loras[0]
            lora["inputs"]["model"] = [unet_id, 0]
            lora["inputs"]["clip"] = [clip_id, 0]
            lora["inputs"]["strength_model"] = float(lora_strength)
            lora["inputs"]["strength_clip"] = 1.0
            sampling["inputs"]["model"] = [lora_id, 0]
            positive["inputs"]["clip"] = [lora_id, 1]
            negative_node["inputs"]["clip"] = [lora_id, 1]
            sampler["inputs"].update({
                "steps": 4,
                "cfg": 1.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            })
        else:
            sampling["inputs"]["model"] = [unet_id, 0]
            positive["inputs"]["clip"] = [clip_id, 0]
            negative_node["inputs"]["clip"] = [clip_id, 0]
            sampler["inputs"].update({
                "steps": 20,
                "cfg": 6.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            })

        if seed is not None:
            sampler["inputs"]["seed"] = int(seed)

        creates = self._nodes_by_type(wf, "CreateVideo")
        if creates:
            creates[0][1]["inputs"]["fps"] = int(fps)

        saves = self._nodes_by_type(wf, "SaveVideo")
        if saves:
            saves[0][1]["inputs"]["filename_prefix"] = "video/PortableAI_VACE"

        return wf

    def queue(self, wf):
        from academic_policy import check_workflow
        check_workflow(wf)
        require_space(root_dir(), 64*1024**2, for_outputs=True)
        client_id = uuid.uuid4().hex
        data = http_json("POST", self.base + "/prompt", {"prompt": wf, "client_id": client_id}, timeout=60)
        pid = data.get("prompt_id")
        if not pid:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
        return pid

    def wait(self, prompt_id):
        timeout = float(self.ccfg.get("timeout_seconds", 3600))
        poll = float(self.ccfg.get("poll_seconds", 1.0))
        transient_grace = float(self.ccfg.get("transient_error_grace_seconds", 120))
        end = time.time() + timeout
        transient_since = None
        last_error = None

        while time.time() < end:
            try:
                require_space(root_dir(), 64*1024**2, for_outputs=True)
                floor=int(self.ccfg.get('min_free_ram_bytes',0))
                if floor:
                    from runtime_policy import memory_info
                    if memory_info()[1]<floor:raise RuntimeError('ComfyUI job stopped to preserve the free RAM reserve')
            except RuntimeError:
                self.interrupt()
                raise
            try:
                hist = http_json(
                    "GET",
                    self.base + "/history/" + urllib.parse.quote(prompt_id),
                    timeout=float(self.ccfg.get('history_timeout_seconds',15)),
                )
                transient_since = None
                last_error = None
            except Exception as exc:
                msg = str(exc).lower()
                transient = any(x in msg for x in (
                    "could not connect",
                    "timed out",
                    "timeout",
                    "connection reset",
                    "connection aborted",
                    "connection refused",
                    "remote end closed",
                    "temporarily unavailable",
                    "forcibly closed",
                    "broken pipe",
                ))
                if not transient:
                    raise

                now = time.time()
                if transient_since is None:
                    transient_since = now
                last_error = exc

                if now - transient_since > transient_grace:
                    raise RuntimeError(
                        f"ComfyUI polling remained unavailable for more than "
                        f"{int(transient_grace)} seconds while waiting for prompt "
                        f"{prompt_id}. Last error: {last_error}"
                    ) from exc

                time.sleep(max(poll, 2.0))
                continue

            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    from comfy_errors import execution_failure
                    raise execution_failure(prompt_id, status)
                if entry.get("outputs") is not None and (
                    status.get("completed") is True
                    or status.get("status_str") == "success"
                    or entry.get("outputs")
                ):
                    return entry

            time.sleep(poll)

        raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

    @staticmethod
    def _collect_file_items(obj):
        found = []
        if isinstance(obj, dict):
            if "filename" in obj and isinstance(obj["filename"], str) and obj.get('type','output')=='output':
                found.append({
                    "filename": obj["filename"],
                    "subfolder": obj.get("subfolder", ""),
                    "type": obj.get("type", "output")
                })
            for v in obj.values():
                found.extend(ComfyBridge._collect_file_items(v))
        elif isinstance(obj, list):
            for v in obj:
                found.extend(ComfyBridge._collect_file_items(v))
        return found

    def fetch_outputs(self, entry, destination: Path):
        destination = media_output(root_dir(), destination)
        destination.mkdir(parents=True, exist_ok=True)
        items = self._collect_file_items(entry.get("outputs", {}))
        if not items:
            outputs = entry.get("outputs", {})
            ids = list(outputs.keys())[:40] if isinstance(outputs, dict) else []
            raise RuntimeError(f"No file outputs found in ComfyUI history; output node ids={ids}. Inspect ComfyUI logs for the full history payload.")
        out = []
        for item in items:
            params = urllib.parse.urlencode(item)
            url = self.base + "/view?" + params
            suffix = Path(item["filename"]).suffix
            dst = destination / (uuid.uuid4().hex[:8] + "_" + Path(item["filename"]).name)
            try:
                with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
                    while block := r.read(1024**2):
                        require_space(root_dir(), len(block), for_outputs=True)
                        f.write(block)
                out.append(str(dst.resolve()))
            except Exception:
                # If /view does not expose this output type, try ComfyUI output directory directly.
                raw = portable_path(resolve_root(self.ccfg["output_dir"]), str(Path(item.get("subfolder", "")) / item["filename"]))
                if raw.exists():
                    require_space(root_dir(), raw.stat().st_size, for_outputs=True)
                    shutil.copy2(raw, dst)
                    out.append(str(dst.resolve()))
                else:
                    raise
        # De-duplicate while preserving order.
        return list(dict.fromkeys(out))

    def run(self, wf, destination: Path):
        pid = self.queue(wf)
        entry = self.wait(pid)
        files = self.fetch_outputs(entry, destination)
        return {"prompt_id": pid, "files": files}
