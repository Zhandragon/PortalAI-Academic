"""Human-readable descriptions of bundled routes, not hardware admission claims."""

# value: (dropdown label, selected-choice explanation)
CHOICES = {
 'media_variant': {
  'auto': ('Automatic | let Nice choose per request', 'Nice chooses standard or a supported uncensored alternate for each request, independently of the chat model. Hardware, memory and task requirements still apply. Tools use standard when Nice supplies no choice.'),
  'standard': ('Standard | media default', 'Use standard media weights unless you explicitly request an alternate for that job. This does not change the chat model. Voice, music and other specialists with no separate variant retain their normal models.'),
  'uncensored': ('Uncensored | where compatible', 'Prefer installed uncensored media weights where the requested task and hardware support them. Missing or non-fitting pairs use a reported standard fallback; an explicit unsupported alternate fails. This does not change the chat model.')},
 'image_profile': {
  'auto': ('Automatic, fit this computer', 'Selects FLUX on a sufficiently large NVIDIA GPU, otherwise SD1.5. Memory is checked after chat releases it. Klein4 is an explicit choice.'),
  'sd15': ('SD1.5 | entry level | CPU / GPU', '512px native images on Windows/Linux x64. CPU: 8 GiB free RAM; Vulkan: 8 GiB, or 10 GiB on shared memory. CUDA: 3 GiB free VRAM + 5 GiB RAM. Standard or DreamShaper 8 follows your media preference.'),
  'klein4': ('Klein4 | midrange | CPU / Vulkan', '128–512px images and reference editing on Windows/Linux x64. Needs 12 GiB free RAM, or 16 GiB with shared GPU memory. Four steps; CPU is slow. Standard/alternate encoders installed. Physical Radeon/Intel/Linux inference is unvalidated.'),
  'flux': ('FLUX | high end | NVIDIA CUDA', 'Larger ComfyUI image workflow: at least 16 GiB free CUDA VRAM + 8 GiB free RAM; alternate encoder requires 20 GiB of each. Native CPU/Vulkan engines do not run this profile; choose Klein4 for those. Linux GPU execution remains unvalidated.')},
 'image_engine': {
  'auto': ('Automatic, fit this computer', 'Uses the selected image model and detected hardware. An explicit model still has to fit; choosing Automatic does not bypass memory or device checks.'),
  'comfyui': ('ComfyUI | NVIDIA / supported Radeon', 'GPU workflow engine: NVIDIA CUDA, or compute-probed ROCm for SD1.5. Windows/Linux runtime support varies by model; physical Radeon/Linux GPU runs remain unvalidated. Klein4 uses a native engine instead.'),
  'sdcpp-vulkan': ('Vulkan | Radeon / Intel / NVIDIA', 'Native SD1.5 or Klein4 on Windows/Linux x64. Requires a working Vulkan device; integrated graphics share system RAM. CPU text encoder/decoder and offloading remain part of the job. Physical Radeon/Intel validation pending.'),
  'sdcpp-cpu': ('CPU | any supported x64 PC | slow', 'Native SD1.5 or Klein4 without GPU acceleration on Windows/Linux x64. Needs 8 GiB free RAM for SD1.5 or 12 GiB for Klein4. Keeps model-specific size and step limits.')},
 'speech_model': {
  'auto': ('Automatic, fit this computer', 'Chooses Whisper large-v3-turbo when CUDA has at least 3 GiB free VRAM and 6 GiB free RAM; otherwise Whisper Base. Windows/Linux x64. Radeon/Intel use CPU transcription.'),
  'base': ('Whisper Base | light | CPU / CUDA', 'Faster, smaller multilingual transcription. Needs 3 GiB free RAM; CPU works on Windows/Linux x64, including Radeon/Intel computers. CUDA acceleration needs at least 1 GiB free VRAM.'),
  'large-v3-turbo': ('Whisper Turbo | accuracy | CPU / CUDA', 'Larger multilingual transcription model. Needs 6 GiB free RAM and 3 GiB free VRAM for CUDA. Automatic device selection keeps this model on CPU if CUDA memory is insufficient; CPU is slower. No ROCm or Vulkan transcription path is enabled.')},
 'voice_engine': {
  'auto': ('Automatic, fit this computer', 'Tries Qwen after reclaiming chat memory on a capable GPU. Piper is the basic English CPU fallback; it does not replace requested cloning, voice design or another language.'),
  'piper': ('Piper | basic English | CPU', 'Lightweight English text-to-speech on Windows/Linux x64. Needs 3 GiB free RAM; one installed voice. No voice cloning or voice design.'),
  'qwen': ('Qwen3-TTS | expressive | NVIDIA / Radeon', 'Multilingual speech, with separate cloning/design tools. Windows/Linux CUDA or compute-probed ROCm: 8 GiB free GPU memory + 6 GiB free RAM (12 GiB on shared Radeon memory). Physical Radeon/Linux GPU speech remains unvalidated.')},
 'text_video_engine': {
  'auto': ('Automatic, fit this computer', 'For video-small: short, silent text-to-video on Windows/Linux x64. 256px/17 frames by default; 128–512px and 5–33 frames within the pixel budget. Needs 14 GiB free RAM, or 18 GiB with shared memory. No reference image or dialogue.'),
  'sdcpp-vulkan': ('Wan 1.3B | Radeon / Intel / NVIDIA', 'For video-small: native Vulkan diffusion with CPU text encoding/decoding. Needs 14 GiB free RAM, or 18 GiB on shared graphics. Standard/experimental alternate follows media preference. Physical Radeon/Intel/Linux generation is unvalidated.'),
  'sdcpp-cpu': ('Wan 1.3B | CPU | very slow', 'For video-small: silent text-only clips without GPU acceleration. Windows/Linux x64; 14 GiB available RAM. This does not animate an input image or replace a dialogue/video editing model.')},
 'reference_video_profile': {
  'auto': ('Automatic, fit this computer', 'For video: Wan 2.2 on Windows NVIDIA; bounded VACE 1.3B on Windows Radeon or Linux CUDA/ROCm. Requires a supported GPU. Does not substitute a text-only video when an image is supplied.'),
  'wan22': ('Wan 2.2 | high end | Windows NVIDIA', 'For video: existing large image-to-video CUDA workflow, intended for the 24 GiB GPU tier. Uses matched standard/alternate motion adapters. Actual free-memory admission still applies. This route is not packaged for Radeon or Linux.'),
  'vace13': ('VACE 1.3B | Radeon / Linux GPU', 'For video: bounded image-conditioned clips, 128–320px and up to 17 frames. Windows ROCm or Linux CUDA/ROCm: 8 GiB free GPU memory + 16 GiB free RAM (24 GiB shared). Physical GPU generation remains unvalidated; CPU diagnostic success is not a product CPU route.')},
 'music_engine': {
  'auto': ('Automatic, fit this computer', 'For music and score-video: compatible ACE-Step GPU first, then MusicGen CPU for explicitly instrumental 1–30s requests. No silent loss of vocals or duration. Rechecks free memory after chat unload. Combined dialogue/editing pipelines retain their task-specific routes.'),
  'acestep-service': ('ACE-Step full | Windows NVIDIA', 'Existing Windows CUDA service with its 5Hz language model. Longer songs and lyrics, 1–480 seconds without silent truncation. Needs 8 GiB free CUDA memory and 8 GiB free RAM after chat unload; loaded service models still determine fit. No separate uncensored checkpoint or runtime content filter was found.'),
  'acestep-scaled': ('ACE-Step turbo | Radeon / Linux GPU', 'Bounded eight-step diffusion with CPU offloading, no 5Hz language model. Windows ROCm or Linux CUDA/ROCm: 6 GiB free GPU memory + 12 GiB free RAM (20 GiB shared), 10–30 seconds. Physical GPU inference remains unvalidated; explicit GPU choices never silently switch to CPU.'),
  'musicgen-cpu': ('MusicGen Small | CPU | instrumentals', 'Windows/Linux x64 without a GPU. Needs 10 GiB free RAM after chat unload; 1–30 seconds, mono 32 kHz, slow. English prompts work best; no sung lyrics. Local standard weights have no separate runtime prompt filter, not a separately abliterated checkpoint. Weights: CC-BY-NC-4.0 (noncommercial).')},
}

TITLES = {'media_variant':'Media models', 'image_profile':'Images', 'image_engine':'Image engine', 'speech_model':'Transcription',
          'voice_engine':'Speech output', 'text_video_engine':'Text-to-video',
          'reference_video_profile':'Image-to-video', 'music_engine':'Music / video score'}

from academic_policy import NOTICE as _ACADEMIC_NOTICE
for _key in CHOICES['media_variant']:
    CHOICES['media_variant'][_key] = (CHOICES['media_variant'][_key][0], _ACADEMIC_NOTICE)

