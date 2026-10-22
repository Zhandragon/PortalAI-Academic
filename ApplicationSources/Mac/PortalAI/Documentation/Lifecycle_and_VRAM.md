# PortalAI lifecycle and VRAM — 2026-10-16

Startup saves pending chat edits and starts/adopts the selected model. Image companions, media workers and science tools load on demand under existing memory and lease gates. Fast image vision uses the matching 2B variant; Balanced tries 4B then 2B under automatic admission. Saved text selection remains separate.

Stop cancels Startup/chat/playback, pauses future mission/schedule work and invalidates delayed restoration. Its owned-worker inventory includes CPU music, Radeon editing/inpainting, music-understanding/CLAP, protein design and FFmpeg/FFprobe/KiCad children as well as the existing workers. The GUI and foreign processes remain excluded. Projection and portable HA Recovery remain separate utilities. Stop is not logout or safe ejection. Normal Exit must finish account sealing before the drive is removed.

PortableAI uses one-owner lifecycle semantics for Qwen VRAM handoff.

1. A heavy GPU tool requests the exclusive GPU lease.
2. PortableAI records a unique Qwen handoff generation and arms a detached recovery watchdog.
3. Qwen is stopped only after its exact command line has been captured.
4. The heavy tool runs.
5. Normal completion restores Qwen once, writes the completion marker, and clears the current generation.
6. If the tool process dies, the watchdog may recover Qwen only if its generation is still current.
7. Any existing listener on port 8080 blocks a second launch. A recognized PortableAI llama-server is adopted; an unrecognized owner is reported as a conflict.

The watchdog has a finite lifetime and never restores Qwen merely because `/health` is temporarily unavailable. This avoids the previous duplicate-listener race where a sleeping/busy/waking Qwen could be mistaken for an absent server.

`Stop all components` terminates PortableAI-owned Qwen/media/science/watchdog processes, verifies dedicated listener ports, clears stale runtime markers, and reports remaining owned processes; a GPU allocation alone is not process ownership.