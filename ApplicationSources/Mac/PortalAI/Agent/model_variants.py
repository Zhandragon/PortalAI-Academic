"""Public model/adapter catalog, not authorization or hardware admission.

Presence checks are optional, read-only and limited to named public assets.
Neither a filename nor a publisher's 'uncensored' label proves model behavior.
"""
from pathlib import Path
import copy

REVISION = '2026-10-16'
MODELS = 'Generative/ComfyUI_windows_portable/ComfyUI/models/'


def asset(path, size=None):
    return {'path': path, **({'bytes': size} if size is not None else {})}


def media(path, size=None):
    return asset(MODELS + path, size)


CATALOG = [
    {
        'id': 'qwen-vl2', 'tools': ['chat'], 'family': 'Qwen3 VL 2B image companion',
        'status': 'parallel', 'selection': 'Settings: Automatic image vision; Fast and low-memory fallback',
        'standard': [asset('LLM/models/Qwen3VL-2B-Instruct-Q4_K_M.gguf', 1107409952),
                     asset('LLM/models/mmproj-Qwen3VL-2B-Instruct-F16.gguf', 819394848)],
        'uncensored': [asset('LLM/models/Huihui-Qwen3-VL-2B-Instruct-abliterated-Q4_K_M.gguf', 1107410528),
                       asset('LLM/models/mmproj-Huihui-Qwen3-VL-2B-Instruct-abliterated-F16.gguf', 819395168)],
        'source': 'https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF',
        'uncensored_source': 'https://huggingface.co/noctrex/Huihui-Qwen3-VL-2B-Instruct-abliterated-GGUF',
        'notes': 'Image-context requests only; retains the saved text model and variant. Pinned provenance is in Agent/small_vision_assets.json. Runtime readiness requires real memory admission; publisher labels do not guarantee behavior.',
    },
    {
        'id': 'qwen-vl4', 'tools': ['chat'], 'family': 'Qwen3 VL 4B image companion',
        'status': 'parallel', 'selection': 'Settings: Automatic image vision; Balanced with 2B memory fallback',
        'standard': [asset('LLM/models/Qwen3VL-4B-Instruct-Q4_K_M.gguf', 2497281664),
                     asset('LLM/models/mmproj-Qwen3VL-4B-Instruct-F16.gguf', 836180256)],
        'uncensored': [asset('LLM/models/Qwen3-VL-4B-Instruct-abliterated.Q4_K_M.gguf', 2497282560),
                       asset('LLM/models/Qwen3-VL-4B-Instruct-abliterated.mmproj-f16.gguf', 836180640)],
        'source': 'https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF',
        'notes': 'Excluded from ordinary automatic text selection. Uses the same GPU lease and owned Stop-fenced handoff as other chat models. Standard never silently replaces an unavailable Uncensored companion.',
    },
    {
        'id': 'qwen4', 'tools': ['chat'], 'family': 'Qwen3 4B text',
        'status': 'parallel', 'selection': 'Model settings: qwen4-q4 / qwen4-abliterated-q4',
        'standard': [asset('LLM/models/Qwen3-4B-Q4_K_M.gguf', 2497280256)],
        'uncensored': [asset('LLM/models/Qwen3-4B-abliterated.Q4_K_M.gguf', 2497280704)],
        'source': 'https://huggingface.co/mradermacher/Qwen3-4B-abliterated-GGUF',
        'notes': 'Text only. Abliterated CPU synthetic inference passed; original retained. Automatic/Fast follows the saved first-pass preference.',
    },
    {
        'id': 'qwen27', 'tools': ['chat', 'video-understand', 'video-analyze', 'vision-benchmark', 'video-vision-benchmark'],
        'family': 'Qwen3.8 27B vision', 'status': 'parallel',
        'selection': 'Model settings: qwen27-standard-q4 / qwen27-q4 / qwen27-q5',
        'standard': [asset('LLM/models/Qwen3.8-27B-Q4_K_M.gguf', 18973870528),
                     asset('LLM/models/mmproj-Qwen3.8-27B-Standard-BF16.gguf', 931145888)],
        'uncensored': [asset('LLM/models/Qwen3.8-27B-Abliterated-Q4_K_M.gguf'),
                       asset('LLM/models/mmproj-Qwen3.8-27B-BF16.gguf')],
        'source': 'https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF',
        'notes': 'Q5 abliterated also retained. Select a matching projector with each checkpoint; Automatic follows the saved variant preference. Large-model inference validation remains separate.',
    },
    {
        'id': 'qwen17', 'tools': ['chat'], 'family': 'Qwen3 1.7B fallback',
        'status': 'parallel', 'standard': [asset('LLM/models/Qwen3-1.7B-Q8_0.gguf', 1834426016)],
        'uncensored': [asset('LLM/models/Qwen3-1.7B-abliterated.Q8_0.gguf', 1834426496)],
        'selection': 'Model settings: qwen1.7-q8 / qwen1.7-abliterated-q8',
        'source': 'https://huggingface.co/mradermacher/Qwen3-1.7B-abliterated-GGUF',
        'notes': 'Automatic low-memory selection follows the saved variant preference. Weights hash-verified. CPU smoke was not run because its free-RAM admission failed; no worker was started.',
    },
    {
        'id': 'flux-klein', 'tools': ['image', 'edit', 'inpaint', 'autoedit', 'video-inpaint'],
        'family': 'FLUX.2 Klein base 9B', 'status': 'parallel',
        'selection': 'saved Images=flux or explicitly requested image profile override; --official/--uncensored chooses its weights',
        'standard': [media('diffusion_models/flux-2-klein-base-9b-fp8.safetensors')],
        'uncensored': [media('diffusion_models/flux-2-klein-base-9b-uncensored.safetensors', 18157185200)],
        'source': 'https://huggingface.co/darknight9121/FLUX.2-klein-base-9B-bucket-uncensored',
        'notes': 'Windows/CUDA FLUX routes only. Community BF16 checkpoint pairs with the separately abliterated FP16 Qwen3 8B encoder. Requires 20 GiB free CUDA-0 VRAM and 20 GiB available RAM after handoff. Publisher labels do not guarantee behavior; GPU inference remains unvalidated.',
    },
    {
        'id': 'flux-text-encoder', 'tools': ['image', 'edit', 'inpaint', 'autoedit', 'video-inpaint'],
        'family': 'FLUX Klein Qwen3 8B text encoder', 'status': 'parallel',
        'standard': [media('text_encoders/qwen_3_8b_fp8mixed.safetensors')],
        'uncensored': [media('text_encoders/flux2-klein-9b-abliterated-qwen3-8b-fp16.safetensors', 16381516808)],
        'source': 'https://huggingface.co/ponpoke/flux2-klein-9b-uncensored-text-encoder',
        'notes': 'Publisher terms accepted by user. Installed from a public packaged copy with identical publisher SHA256/size; linked only to alternate workflows. FP16 weights and Qwen3 8B header match the existing CLIPLoader/flux2 detector. Full GPU inference remains unvalidated; no GGUF plugin was installed.',
    },
    {
        'id': 'sd15', 'tools': ['image'], 'family': 'Stable Diffusion 1.5',
        'status': 'parallel',
        'selection': 'saved preference / --official / --uncensored; auto profile retains hardware selection',
        'standard': [media('checkpoints/v1-5-pruned-emaonly.safetensors')],
        'uncensored': [media('checkpoints/DreamShaper_8_pruned.safetensors', 2132625894)],
        'source': 'https://huggingface.co/Lykon/DreamShaper',
        'notes': 'Native CPU/Vulkan and ComfyUI small profile. Alternate is DreamShaper 8, a community SD1.5 fine-tune with publisher-described NSFW support, not an abliterated release or behavior guarantee. No separate safety checker in these workflows. FLUX/Wan adapters are incompatible.',
    },
    {
        'id': 'klein4', 'tools': ['image', 'edit', 'inpaint', 'autoedit', 'video-inpaint'],
        'family': 'FLUX Klein 4B native CPU/Vulkan', 'status': 'parallel_encoder',
        'selection': 'saved Images=klein4 or explicitly requested image profile override; edit/inpaint/autoedit --edit-profile klein4; scaled auto editing on Radeon/Linux',
        'standard': [asset('LLM/models/Qwen3-4B-Q4_K_M.gguf', 2497280256)],
        'uncensored': [media('text_encoders/flux2-klein-4b-uncensored-q4_k_m.gguf', 2497280416)],
        'shared': [media('diffusion_models/flux-2-klein-4b-Q4_0.gguf', 2460378560), media('vae/flux2-vae.safetensors', 336211292)],
        'source': 'https://huggingface.co/ponpoke/flux2-klein-4b-uncensored-text-encoder',
        'notes': 'Windows/Linux x64 CPU/Vulkan; dedicated Radeon/Intel/integrated devices require a working Vulkan probe and memory admission. Shared distilled DiT with matched standard or abliterated Qwen3 4B encoder; no separate alternate DiT claimed. 12 GiB available RAM, 16 GiB for shared GPU memory; 128..512px, four default steps. Alternate encoder has publisher noncommercial terms. Bounded Windows CPU generation/reference editing/cancellation passed. Physical Radeon/Intel and Linux inference remain unvalidated.',
    },
    {
        'id': 'pix2pix', 'tools': ['edit', 'inpaint', 'autoedit', 'video-inpaint'],
        'family': 'InstructPix2Pix scaled Radeon/Linux editing', 'status': 'no_verified_alternative_installed',
        'notes': 'No compatible alternate verified. Existing runtime already has no diffusers safety checker; this does not make the checkpoint abliterated. Scaled automatic editing now uses the distinct native Klein4 route; --edit-profile pix2pix retains this original model. Do not substitute a FLUX LoRA.',
    },
    {
        'id': 'wan22', 'tools': ['video', 'video-range-edit', 'dialogue-video'],
        'family': 'Wan2.2 I2V 14B paired LightX2V LoRAs', 'status': 'parallel',
        'selection': 'saved preference / --official / --uncensored',
        'standard': [media('loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors'),
                     media('loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors')],
        'uncensored': [media('loras/Wan2.2_LightX2V_high_n54vv.safetensors', 1245752600),
                       media('loras/Wan2.2_LightX2V_low_n54vv.safetensors', 1245752600)],
        'source': 'https://huggingface.co/rzgar/Wan2.2_LightX2V_4Step_Uncensored',
        'notes': 'Windows/CUDA motion-generation stage only, on the same standard high/low base weights. Keep each high/low pair together. This does not change speech, lip-sync, music or VACE models in a combined tool. Radeon/Linux VACE rejects --uncensored.',
    },
    {
        'id': 'wan13', 'tools': ['video-small'], 'family': 'Wan2.1 T2V 1.3B',
        'status': 'parallel_experimental', 'selection': 'saved preference / --official / --uncensored',
        'standard': [media('diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors', 2838303560)],
        'uncensored': [media('diffusion_models/wan_1.3B_exp_e14.safetensors', 2838077328)],
        'source': 'https://huggingface.co/NSFW-API/NSFW_Wan_1.3b',
        'notes': 'Native CPU/Vulkan text-only route; silent short clips. Publisher warns of weaker general-purpose quality. Experimental fine-tune, not an ablation guarantee. Standard text encoder/VAE shared. No compatible LoRAs configured; physical inference unvalidated.',
    },
    {
        'id': 'vace', 'tools': ['video-edit', 'video', 'video-range-edit', 'dialogue-video'],
        'family': 'Wan2.1 VACE 14B / scaled 1.3B', 'status': 'no_verified_alternative_installed',
        'standard': [media('diffusion_models/wan2.1_vace_14B_fp16.safetensors'),
                     media('diffusion_models/wan2.1_vace_1.3B_fp16.safetensors')],
        'uncensored': [], 'notes': 'VACE editing/reference model is distinct from Wan2.2 I2V and Wan1.3B T2V. Do not interchange checkpoints or LoRAs. CausVid is an acceleration adapter, not an uncensored variant.',
    },
    {
        'id': 'voice', 'tools': ['voice-say', 'voice-clone', 'voice-design', 'voice-custom', 'dialogue-video', 'video-dialogue'],
        'family': 'Qwen3-TTS Base / CustomVoice / VoiceDesign; Piper fallback',
        'status': 'no_verified_alternative_installed',
        'notes': 'No matching separate uncensored release verified. Keep voice identity, language and cloning requirements; text-chat Qwen ablations cannot replace TTS weights.',
    },
    {
        'id': 'music', 'tools': ['music', 'score-video', 'audio-inpaint', 'dialogue-video'],
        'family': 'ACE-Step 1.5 turbo / 5Hz LM; MusicGen Small CPU', 'status': 'no_verified_alternative_installed',
        'notes': 'No matching separate uncensored release verified. Standard music/repaint routes remain. MusicGen CPU is a separate instrumental model with no runtime prompt filter (1..30s, noncommercial weights), not a music censorship variant.',
    },
    {
        'id': 'sfx', 'tools': ['sfx', 'video-sfx', 'sfx-inpaint', 'audio-inpaint'],
        'family': 'MMAudio small / large; spectral repair', 'status': 'no_verified_alternative_installed',
        'notes': '--variant in MMAudio selects architecture/size, not censorship. No separate uncensored release verified; do not pass uncensored as an MMAudio variant.',
    },
    {
        'id': 'musetalk', 'tools': ['lip-sync', 'video-dialogue', 'dialogue-video'],
        'family': 'MuseTalk', 'status': 'no_verified_alternative_installed',
        'notes': 'Audio-driven mouth motion; no separate uncensored model verified. Motion-model choice does not change MuseTalk.',
    },
    {
        'id': 'understanding', 'tools': ['transcribe', 'music-understand', 'music-analyze', 'video-understand', 'video-analyze'],
        'family': 'Whisper / MOSS / CLAP / Demucs', 'status': 'no_verified_alternative_installed',
        'notes': 'No corresponding alternate verified. Transcription, ranking and source separation are different tasks from generative chat; swapping a Qwen chat ablation cannot preserve these capabilities.',
    },
    {
        'id': 'mask', 'tools': ['mask', 'inpaint', 'autoedit', 'video-inpaint'],
        'family': 'SAM2 / GroundingDINO', 'status': 'not_applicable',
        'notes': 'Segmentation and object detection. No separate refusal-trained/abliterated variant configured or needed to select the downstream image model.',
    },
    {
        'id': 'adapters', 'tools': ['video', 'video-edit'], 'family': 'Other installed specialist LoRAs',
        'status': 'not_applicable',
        'notes': 'CausVid accelerates VACE. Existing appearance adapters are task-specific, not standard/uncensored pairs; no automatic stacking or substitution. Only use architecture/stage-matched adapters. Their presence is not evidence of provenance or inference quality.',
    },
    {
        'id': 'deterministic', 'tools': ['media-info', 'audio-edit', 'audio-mix', 'video-adjust', 'mux', 'sound-video', 'preview', 'science'],
        'family': 'FFmpeg / deterministic processing / scientific solvers', 'status': 'not_applicable',
        'notes': 'No standard/uncensored model pair applies to these transformations or solvers.',
    },
]

# Runtime inspection is not a claim about every learned behavior. Keep these
# distinctions machine-readable so discovery never equates no alternate with
# inability to process a request.
for _row in CATALOG:
    if _row['id'] in {'vace', 'voice', 'music', 'sfx', 'musetalk', 'pix2pix'}:
        _row['status'] = 'standard_local_no_filter_found'
        _row['filtering'] = 'No separate runtime prompt/output content filter found in the installed route; checkpoint behavior is not guaranteed.'
        _row['replacement_needed'] = 'No demonstrated content-filter blocker; retain the task-matched local model.'
        _row['notes'] += ' Lack of an alternate release does not imply censorship. Use the normal local route. See Documentation/Media_Previews_20261012.txt for audit scope and differences.'
    if _row['id'] == 'vace':
        _row['closest_alternatives'] = [
            {'tool':'video-inpaint','model':'Klein4 alternate encoder','difference':'Masked framewise image edits; temporal flicker possible; does not replace VACE motion/control conditioning.'},
            {'tool':'video-small','model':'Wan1.3B experimental alternate','difference':'Silent text-only generation; loses image/video/mask conditioning.'}]
    if _row['id'] == 'understanding':
        _row['notes'] += ' Whisper/CLAP/Demucs have no separate content filter identified. MOSS is a generative language specialist: learned refusal behavior has not been audited; no capability-equivalent alternate verified.'


def catalog(tool=None, *, root=None, check_files=False):
    rows = copy.deepcopy([row for row in CATALOG if tool is None or tool in row['tools']])
    if not rows:
        raise ValueError('No model-variant entry for this tool: ' + str(tool))
    if check_files:
        from runtime_policy import portable_path
        for row in rows:
            for variant in ('standard', 'uncensored', 'shared'):
                for entry in row.get(variant, []):
                    try:
                        path = portable_path(Path(root), entry['path'])
                        stat = path.stat()
                        with path.open('rb') as handle:
                            handle.read(1)
                        entry['present_readable'] = path.is_file()
                        entry['size_matches'] = stat.st_size == entry['bytes'] if 'bytes' in entry else None
                    except (OSError, ValueError):
                        entry.update(present_readable=False, size_matches=False)
    return {
        'success': True, 'tool': 'model-variants', 'revision': REVISION,
        'default': 'standard', 'uncensored_requires_explicit_request': False,
        'default_source': 'Academic policy: standard only; alternate models are unavailable.',
        'uncensored_available': False,
        'chat_default': 'Academic: standard only; automatic hardware fit',
        'media_default': 'standard', 'edition': 'Academic', 'variant_locked': True,
        'image_profile_policy': 'Nice and full missions follow current saved Images. Named choices stay pinned, including against stale profile=auto/sd15. Only a user-requested one-off model change uses override_saved_profile=true with profile, or CLI --override-saved-profile with --profile. Variant alone never changes the family. Admission failures are reported, not silently downgraded. Human CLI profile overrides retain their normal behavior.',
        'policy': 'Academic: standard models only. Alternate catalog entries are reference metadata and unavailable to students. Keep normal specialists, memory/storage/account/Stop gates.',
        'files_checked': bool(check_files), 'hardware_probed': False,
        'validation': 'Catalog is public route metadata. Optional file checks are presence/size/readability only, not fresh hashes or inference. Historical hashes: Maintenance/Imports/media-variants-verified-20261011.json and per-model import receipts.',
        'models': rows,
    }


def require_flux_alternate(root, hardware=None):
    """Admit the larger 16-bit alternate once after chat handoff, before loading.

    This is deliberately separate from the standard FP8 image profile. A 16 GB
    encoder must not inherit the original eight-GiB host-memory admission floor.
    """
    from academic_policy import NOTICE
    raise ValueError(NOTICE)


def first_pass(root, family, *, policy=None, hardware=None):
    """Saved preference is best effort; explicit CLI flags bypass this resolver.

    FLUX callers must hold the GPU lease and have reclaimed chat before calling.
    Other families retain their existing runtime admission after selection.
    """
    from academic_policy import NOTICE
    return 'official', NOTICE

# Academic tool discovery exposes usable standard routes. Historical alternate
# names remain in public documentation, but are not instructions to load them.
from academic_policy import NOTICE as _ACADEMIC_NOTICE, blocked_name as _academic_blocked
for _row in CATALOG:
    _alternates = _row.pop('uncensored', [])
    if _alternates:
        _row['unavailable_variants'] = {'uncensored': {'available': False, 'reason': _ACADEMIC_NOTICE}}
        _row['status'] = 'academic_standard_only'
    for _key in ('uncensored_source', 'closest_alternatives', 'replacement_needed'):
        _row.pop(_key, None)
    if _academic_blocked(_row.get('source', '')):
        _row.pop('source', None)
    _row['selection'] = 'Academic: use the standard family and saved hardware/profile selection.'
    _sentences = _row.get('notes', '').split('. ')
    _row['notes'] = '. '.join(_s for _s in _sentences if not _academic_blocked(_s) and 'alternate' not in _s.casefold())
    _row['academic_notice'] = _ACADEMIC_NOTICE
    if 'filtering' in _row:
        _row['filtering'] += ' Academic instruction guidance does not add a separate media output classifier.'
