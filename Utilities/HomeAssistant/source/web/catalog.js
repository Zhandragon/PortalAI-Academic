export const CATALOG = {
  "surfaces": [
    {
      "desktop_id": "welcome",
      "label": "Welcome",
      "source_modules": [
        "reference/PortalAI/ControlCenter/public_welcome.py",
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py"
      ],
      "scope": "Branding, overview, help; browser-local presentation."
    },
    {
      "desktop_id": "accounts",
      "label": "Accounts",
      "source_modules": [
        "reference/PortalAI/ControlCenter/account_gate.py",
        "reference/PortalAI/ControlCenter/accounts_page.py",
        "reference/PortalAI/ControlCenter/account_ui.py",
        "reference/PortalAI/ControlCenter/account_switch.py",
        "reference/PortalAI/ControlCenter/admin_profile_ui.py",
        "reference/PortalAI/ControlCenter/account_reset_ui.py"
      ],
      "scope": "Real login/enrollment/password/admin/recovery/export/switch/logout flows; staged port, fallback initially."
    },
    {
      "desktop_id": "controls",
      "label": "Controls",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/lifecycle_control.py"
      ],
      "scope": "Six primary buttons, runtime/startup state, Control Log and contextual actions."
    },
    {
      "desktop_id": "chat",
      "label": "Chat",
      "source_modules": [
        "reference/PortalAI/ControlCenter/native_chat.py",
        "reference/PortalAI/ControlCenter/portal_frontend_v15136.py",
        "reference/PortalAI/ControlCenter/chat_catalog.py",
        "reference/PortalAI/ControlCenter/persistent_memory.py",
        "reference/PortalAI/ControlCenter/memory_items_ui.py",
        "reference/PortalAI/ControlCenter/chat_effort_ui.py"
      ],
      "scope": "Transcript, streaming, tools, history, memory, attachments, preferences, media, microphone."
    },
    {
      "desktop_id": "activity",
      "label": "Runtime",
      "source_modules": [
        "reference/PortalAI/ControlCenter/runtime_activity.py",
        "reference/PortalAI/ControlCenter/activity_monitor.py",
        "reference/PortalAI/ControlCenter/windows_gpu_counters.py"
      ],
      "scope": "Read-only account-scoped runtime/CPU/GPU observations; no process argv export."
    },
    {
      "desktop_id": "runtime",
      "label": "Models",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/bundle_inventory.py",
        "reference/PortalAI/ControlCenter/runtime_health.py"
      ],
      "scope": "Installed/loaded/sleeping/healthy state and capability detail; do not conflate them."
    },
    {
      "desktop_id": "installed",
      "label": "Packages",
      "source_modules": [
        "reference/PortalAI/ControlCenter/packages_page.py",
        "reference/PortalAI/ControlCenter/bundle_inventory.py"
      ],
      "scope": "Package/capability inventories and help; file presence does not prove inference."
    },
    {
      "desktop_id": "settings",
      "label": "Settings",
      "source_modules": [
        "reference/PortalAI/ControlCenter/settings_page.py",
        "reference/PortalAI/ControlCenter/settings_style.py",
        "reference/PortalAI/ControlCenter/media_choices.py"
      ],
      "scope": "Chat model and memory / Media defaults subtabs, draft preservation, immediate model-pair save, fit probes."
    },
    {
      "desktop_id": "persistence",
      "label": "Persistence",
      "source_modules": [
        "reference/PortalAI/ControlCenter/persistence_page.py",
        "reference/PortalAI/ControlCenter/mission_settings.py",
        "reference/PortalAI/ControlCenter/schedule_settings.py"
      ],
      "scope": "Missions and Schedules subtabs; explicit reviewed resume, arm/disarm, recoverable list removal."
    },
    {
      "desktop_id": "maintenance",
      "label": "Maintenance",
      "source_modules": [
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py",
        "reference/PortalAI/ControlCenter/maintenance_cleanup.py",
        "reference/PortalAI/ControlCenter/profile_diagnostics.py",
        "reference/PortalAI/ControlCenter/settings_page.py"
      ],
      "scope": "Reports, diagnostics, storage reserves, review-only duplicate scan, cleanup and dependency probes."
    },
    {
      "desktop_id": "help",
      "label": "Help",
      "source_modules": [
        "reference/PortalAI/ControlCenter/help_topics.py",
        "reference/PortalAI/ControlCenter/public_welcome.py",
        "reference/PortalAI/ControlCenter/PortableAI_GUI.py"
      ],
      "scope": "Help topics and branded artwork; browser-local rendering."
    }
  ],
  "themes": {
    "LIGHT_COLORS": {
      "bg": "#EEE7DC",
      "panel": "#F8F3EA",
      "panel2": "#E9E0D2",
      "panel3": "#DED1BC",
      "card": "#FFFDF8",
      "card_hover": "#F7F0E5",
      "text": "#202224",
      "muted": "#625E59",
      "muted2": "#7C725F",
      "accent": "#3E91A2",
      "accent2": "#1F6F82",
      "good": "#2E8062",
      "warn": "#9D7027",
      "bad": "#A9514C",
      "button": "#E6DCCB",
      "button_hover": "#D9CBB3",
      "danger": "#7C403E",
      "danger_hover": "#66312F",
      "border": "#7B5A22",
      "gold_mid": "#A87D32",
      "gold_shine": "#D9BE78",
      "outline": "#343638",
      "border_soft": "#6E6E6B",
      "shadow": "#1E2022",
      "model_bg": "#F3ECE1"
    },
    "DARK_COLORS": {
      "bg": "#111315",
      "panel": "#1C1E20",
      "panel2": "#252729",
      "panel3": "#302D27",
      "card": "#242628",
      "card_hover": "#2D3032",
      "text": "#F2ECE2",
      "muted": "#B7AFA4",
      "muted2": "#9D9282",
      "accent": "#58AFC1",
      "accent2": "#7CC4D3",
      "good": "#63B88E",
      "warn": "#C89B4A",
      "bad": "#D17770",
      "button": "#2A2D2F",
      "button_hover": "#363A3D",
      "danger": "#6C3534",
      "danger_hover": "#83423F",
      "border": "#806027",
      "gold_mid": "#B0863A",
      "gold_shine": "#D6BA70",
      "outline": "#070809",
      "border_soft": "#4B4E50",
      "shadow": "#000000",
      "model_bg": "#101214"
    }
  },
  "media": {
    "CHOICES": {
      "media_variant": {
        "auto": [
          "Automatic | let Nice choose per request",
          "Nice chooses standard or a supported uncensored alternate for each request, independently of the chat model. Hardware, memory and task requirements still apply. Tools use standard when Nice supplies no choice."
        ],
        "standard": [
          "Standard | media default",
          "Use standard media weights unless you explicitly request an alternate for that job. This does not change the chat model. Voice, music and other specialists with no separate variant retain their normal models."
        ],
        "uncensored": [
          "Uncensored | where compatible",
          "Prefer installed uncensored media weights where the requested task and hardware support them. Missing or non-fitting pairs use a reported standard fallback; an explicit unsupported alternate fails. This does not change the chat model."
        ]
      },
      "image_profile": {
        "auto": [
          "Automatic, fit this computer",
          "Selects FLUX on a sufficiently large NVIDIA GPU, otherwise SD1.5. Memory is checked after chat releases it. Klein4 is an explicit choice."
        ],
        "sd15": [
          "SD1.5 | entry level | CPU / GPU",
          "512px native images on Windows/Linux x64. CPU: 8 GiB free RAM; Vulkan: 8 GiB, or 10 GiB on shared memory. CUDA: 3 GiB free VRAM + 5 GiB RAM. Standard or DreamShaper 8 follows your media preference."
        ],
        "klein4": [
          "Klein4 | midrange | CPU / Vulkan",
          "128\u2013512px images and reference editing on Windows/Linux x64. Needs 12 GiB free RAM, or 16 GiB with shared GPU memory. Four steps; CPU is slow. Standard/alternate encoders installed. Physical Radeon/Intel/Linux inference is unvalidated."
        ],
        "flux": [
          "FLUX | high end | NVIDIA CUDA",
          "Larger ComfyUI image workflow: at least 16 GiB free CUDA VRAM + 8 GiB free RAM; alternate encoder requires 20 GiB of each. Native CPU/Vulkan engines do not run this profile; choose Klein4 for those. Linux GPU execution remains unvalidated."
        ]
      },
      "image_engine": {
        "auto": [
          "Automatic, fit this computer",
          "Uses the selected image model and detected hardware. An explicit model still has to fit; choosing Automatic does not bypass memory or device checks."
        ],
        "comfyui": [
          "ComfyUI | NVIDIA / supported Radeon",
          "GPU workflow engine: NVIDIA CUDA, or compute-probed ROCm for SD1.5. Windows/Linux runtime support varies by model; physical Radeon/Linux GPU runs remain unvalidated. Klein4 uses a native engine instead."
        ],
        "sdcpp-vulkan": [
          "Vulkan | Radeon / Intel / NVIDIA",
          "Native SD1.5 or Klein4 on Windows/Linux x64. Requires a working Vulkan device; integrated graphics share system RAM. CPU text encoder/decoder and offloading remain part of the job. Physical Radeon/Intel validation pending."
        ],
        "sdcpp-cpu": [
          "CPU | any supported x64 PC | slow",
          "Native SD1.5 or Klein4 without GPU acceleration on Windows/Linux x64. Needs 8 GiB free RAM for SD1.5 or 12 GiB for Klein4. Keeps model-specific size and step limits."
        ]
      },
      "speech_model": {
        "auto": [
          "Automatic, fit this computer",
          "Chooses Whisper large-v3-turbo when CUDA has at least 3 GiB free VRAM and 6 GiB free RAM; otherwise Whisper Base. Windows/Linux x64. Radeon/Intel use CPU transcription."
        ],
        "base": [
          "Whisper Base | light | CPU / CUDA",
          "Faster, smaller multilingual transcription. Needs 3 GiB free RAM; CPU works on Windows/Linux x64, including Radeon/Intel computers. CUDA acceleration needs at least 1 GiB free VRAM."
        ],
        "large-v3-turbo": [
          "Whisper Turbo | accuracy | CPU / CUDA",
          "Larger multilingual transcription model. Needs 6 GiB free RAM and 3 GiB free VRAM for CUDA. Automatic device selection keeps this model on CPU if CUDA memory is insufficient; CPU is slower. No ROCm or Vulkan transcription path is enabled."
        ]
      },
      "voice_engine": {
        "auto": [
          "Automatic, fit this computer",
          "Tries Qwen after reclaiming chat memory on a capable GPU. Piper is the basic English CPU fallback; it does not replace requested cloning, voice design or another language."
        ],
        "piper": [
          "Piper | basic English | CPU",
          "Lightweight English text-to-speech on Windows/Linux x64. Needs 3 GiB free RAM; one installed voice. No voice cloning or voice design."
        ],
        "qwen": [
          "Qwen3-TTS | expressive | NVIDIA / Radeon",
          "Multilingual speech, with separate cloning/design tools. Windows/Linux CUDA or compute-probed ROCm: 8 GiB free GPU memory + 6 GiB free RAM (12 GiB on shared Radeon memory). Physical Radeon/Linux GPU speech remains unvalidated."
        ]
      },
      "text_video_engine": {
        "auto": [
          "Automatic, fit this computer",
          "For video-small: short, silent text-to-video on Windows/Linux x64. 256px/17 frames by default; 128\u2013512px and 5\u201333 frames within the pixel budget. Needs 14 GiB free RAM, or 18 GiB with shared memory. No reference image or dialogue."
        ],
        "sdcpp-vulkan": [
          "Wan 1.3B | Radeon / Intel / NVIDIA",
          "For video-small: native Vulkan diffusion with CPU text encoding/decoding. Needs 14 GiB free RAM, or 18 GiB on shared graphics. Standard/experimental alternate follows media preference. Physical Radeon/Intel/Linux generation is unvalidated."
        ],
        "sdcpp-cpu": [
          "Wan 1.3B | CPU | very slow",
          "For video-small: silent text-only clips without GPU acceleration. Windows/Linux x64; 14 GiB available RAM. This does not animate an input image or replace a dialogue/video editing model."
        ]
      },
      "reference_video_profile": {
        "auto": [
          "Automatic, fit this computer",
          "For video: Wan 2.2 on Windows NVIDIA; bounded VACE 1.3B on Windows Radeon or Linux CUDA/ROCm. Requires a supported GPU. Does not substitute a text-only video when an image is supplied."
        ],
        "wan22": [
          "Wan 2.2 | high end | Windows NVIDIA",
          "For video: existing large image-to-video CUDA workflow, intended for the 24 GiB GPU tier. Uses matched standard/alternate motion adapters. Actual free-memory admission still applies. This route is not packaged for Radeon or Linux."
        ],
        "vace13": [
          "VACE 1.3B | Radeon / Linux GPU",
          "For video: bounded image-conditioned clips, 128\u2013320px and up to 17 frames. Windows ROCm or Linux CUDA/ROCm: 8 GiB free GPU memory + 16 GiB free RAM (24 GiB shared). Physical GPU generation remains unvalidated; CPU diagnostic success is not a product CPU route."
        ]
      },
      "music_engine": {
        "auto": [
          "Automatic, fit this computer",
          "For music and score-video: compatible ACE-Step GPU first, then MusicGen CPU for explicitly instrumental 1\u201330s requests. No silent loss of vocals or duration. Rechecks free memory after chat unload. Combined dialogue/editing pipelines retain their task-specific routes."
        ],
        "acestep-service": [
          "ACE-Step full | Windows NVIDIA",
          "Existing Windows CUDA service with its 5Hz language model. Longer songs and lyrics, 1\u2013480 seconds without silent truncation. Needs 8 GiB free CUDA memory and 8 GiB free RAM after chat unload; loaded service models still determine fit. No separate uncensored checkpoint or runtime content filter was found."
        ],
        "acestep-scaled": [
          "ACE-Step turbo | Radeon / Linux GPU",
          "Bounded eight-step diffusion with CPU offloading, no 5Hz language model. Windows ROCm or Linux CUDA/ROCm: 6 GiB free GPU memory + 12 GiB free RAM (20 GiB shared), 10\u201330 seconds. Physical GPU inference remains unvalidated; explicit GPU choices never silently switch to CPU."
        ],
        "musicgen-cpu": [
          "MusicGen Small | CPU | instrumentals",
          "Windows/Linux x64 without a GPU. Needs 10 GiB free RAM after chat unload; 1\u201330 seconds, mono 32 kHz, slow. English prompts work best; no sung lyrics. Local standard weights have no separate runtime prompt filter, not a separately abliterated checkpoint. Weights: CC-BY-NC-4.0 (noncommercial)."
        ]
      }
    },
    "TITLES": {
      "media_variant": "Media models",
      "image_profile": "Images",
      "image_engine": "Image engine",
      "speech_model": "Transcription",
      "voice_engine": "Speech output",
      "text_video_engine": "Text-to-video",
      "reference_video_profile": "Image-to-video",
      "music_engine": "Music / video score"
    }
  }
};
