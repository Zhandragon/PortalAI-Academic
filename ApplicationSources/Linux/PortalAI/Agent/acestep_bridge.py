from __future__ import annotations
from pathlib import Path
import json, time, urllib.parse, urllib.request, uuid, shutil
from _common import load_config, resolve_root, http_json, root_dir


def _transient_connection_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    markers = (
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
    )
    return any(m in msg for m in markers)


class AceStepBridge:
    def __init__(self):
        self.cfg = load_config()
        self.acfg = self.cfg["acestep"]
        self.base = self.acfg["base_url"].rstrip("/")

    def health(self):
        return http_json("GET", self.base + "/health", timeout=10)

    def generate(
        self,
        prompt: str,
        lyrics: str | None = None,
        duration: int | None = None,
        instrumental: bool = False,
    ):
        payload = {
            "prompt": prompt,
            # Never silently turn an omitted duration into a 60-second job.
            # Video-associated calls pass an explicit measured duration; standalone
            # music gets a short safe fallback.
            "audio_duration": int(duration if duration is not None else self.acfg.get("safe_default_duration", 15)),
            "instrumental": bool(instrumental),
        }
        if lyrics:
            payload["lyrics"] = lyrics

        resp = http_json("POST", self.base + "/release_task", payload, timeout=60)
        data = resp.get("data", resp)
        if isinstance(data, dict):
            task_id = data.get("task_id") or data.get("id")
        else:
            task_id = None

        if not task_id:
            raise RuntimeError(f"ACE-Step did not return task_id: {resp}")

        timeout = float(self.acfg.get("timeout_seconds", 3600))
        poll = float(self.acfg.get("poll_seconds", 2.0))
        transient_grace = float(self.acfg.get("transient_error_grace_seconds", 180))
        end = time.time() + timeout

        result_obj = None
        transient_since = None
        last_transient_error = None

        while time.time() < end:
            try:
                q = http_json(
                    "POST",
                    self.base + "/query_result",
                    {"task_id_list": [task_id]},
                    timeout=15,
                )
                transient_since = None
                last_transient_error = None
            except Exception as exc:
                if not _transient_connection_error(exc):
                    raise

                now = time.time()
                if transient_since is None:
                    transient_since = now
                last_transient_error = exc

                # ACE-Step can briefly stop answering HTTP while the GPU is busy.
                # Do not abandon an already-submitted task on the first dropped poll.
                if now - transient_since > transient_grace:
                    raise RuntimeError(
                        f"ACE-Step polling remained unavailable for more than "
                        f"{int(transient_grace)} seconds while waiting for task "
                        f"{task_id}. Last error: {last_transient_error}"
                    ) from exc

                time.sleep(max(poll, 3.0))
                continue

            rows = q.get("data", q)
            if isinstance(rows, dict):
                rows = [rows]
            row = rows[0] if isinstance(rows, list) and rows else {}
            status = row.get("status")

            if status == 2:
                raise RuntimeError(f"ACE-Step generation failed: {row}")

            if status == 1:
                raw_result = row.get("result")
                if isinstance(raw_result, str):
                    try:
                        raw_result = json.loads(raw_result)
                    except json.JSONDecodeError:
                        pass
                result_obj = raw_result
                break

            time.sleep(poll)

        if result_obj is None:
            raise TimeoutError(f"Timed out waiting for ACE-Step task {task_id}")

        return task_id, result_obj

    @staticmethod
    def _find_audio_urls(obj):
        found = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("file", "audio_url", "url") and isinstance(v, str):
                    if "/v1/audio" in v or v.lower().endswith(
                        (".wav", ".mp3", ".flac", ".m4a", ".ogg")
                    ):
                        found.append(v)
                found.extend(AceStepBridge._find_audio_urls(v))
        elif isinstance(obj, list):
            for v in obj:
                found.extend(AceStepBridge._find_audio_urls(v))
        return list(dict.fromkeys(found))

    def download(self, result_obj, destination: Path):
        from media_paths import media_output
        destination = media_output(root_dir(), destination)
        destination.mkdir(parents=True, exist_ok=True)
        urls = self._find_audio_urls(result_obj)

        if not urls:
            raise RuntimeError(f"No audio URL/path found in ACE-Step result: {result_obj}")

        outputs = []
        for u in urls:
            if u.startswith("http://") or u.startswith("https://"):
                url = u
            elif u.startswith("/"):
                url = self.base + u
            else:
                url = self.base + "/v1/audio?" + urllib.parse.urlencode({"path": u})

            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            source_name = Path(qs.get("path", ["music.wav"])[0]).name or "music.wav"
            if not Path(source_name).suffix:
                source_name += ".wav"

            dst = destination / (uuid.uuid4().hex[:8] + "_" + source_name)

            last_error = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=180) as r, open(dst, "wb") as f:
                        shutil.copyfileobj(r, f)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2 and _transient_connection_error(exc):
                        time.sleep(3)
                        continue
                    raise

            if last_error is not None:
                raise last_error

            outputs.append(str(dst.resolve()))

        return outputs
