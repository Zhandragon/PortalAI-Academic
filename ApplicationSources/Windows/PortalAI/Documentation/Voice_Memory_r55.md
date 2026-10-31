# Windows r55: hands-free speech, memory handoff and voice visualization

Hands-free listens, transcribes with local CPU Whisper, submits the recognized
message, retains Nice's completed answer in chat, speaks it with the selected local English voice, then returns to listening. Microphone capture pauses during
playback to avoid transcribing Nice. Mic dictation still places text in the draft
without sending it. End hands-free and Stop cancel voice activity.

## Memory admission and model restoration

An RTX 3090's 24 GiB VRAM does not replace system RAM. A large Qwen model and its
context can leave too little host RAM for voice even with full GPU offloading.
The previous hands-free/direct-mic paths bypassed the existing tool memory
handoff. Both now use Agent/voice_memory.py through ControlCenter/chat_voice.py.

When fresh admission allows CPU speech, Nice stays loaded. A typed pre-inference
memory rejection acquires the existing GPU lease, releases only this portable
root's owned idle chat model, rechecks real memory, and runs the requested voice
stage. The exact model command is restored and health checked before continuation.
The original account/Stop generation remains binding; another model operation
can suppress stale restoration. Foreign listeners are never killed by port.
Waiting for the lease is cancellable and bounded to 60 seconds.

CPU Whisper base and Piper retain their 3 GiB available-RAM admission including
reserve. Other configured speech models retain their own requirements. No RAM or
VRAM safety floor is lowered; no model, language or voice is silently substituted.
If other applications still leave too little RAM after release, a clear error
reports required and available memory. A request may retry once only for a typed
admission failure before inference. Unknown worker failures, OOMs, playback
errors and completed audio are not replayed. Long replies use bounded speech
chunks; low memory may require a handoff for each chunk, which adds latency.
STT/TTS workers exit after their stage, releasing their allocations.

## Visualizer and controls

The existing PortalAI theme frames a compact voice card above the composer. Its
waveform pulses turquoise with microphone/reply amplitude and settles to gold.
Nice's orb uses the existing PortalAI logo PNG unchanged. Its gold/black frame
stays fixed; only its small internal turquoise portal is animated. The orb is stationary while Nice
is listening, thinking, transcribing or idle, and animates only during speech.
Click its orb or Mute microphone to discard microphone input; Nice's playback
remains audible. Unmuting begins a fresh utterance without buffered muted audio.

The waveform uses native Tk canvas vectors without new packages. The logo is
read once; 24 tiny center frames are cached per GUI (under 100 KiB decoded pixel
storage, including the base logo). Animation selects a cached image; no image
decoding or rotation runs inside an animation callback. The source PNG is unchanged.
Canvas items are reused, unchanged coordinates/styles are not sent to Tk, and
active updates are capped at 20 FPS. Settled listening skips canvas drawing and
polls status every 150 ms; hidden/destroyed cards cancel their timer and detach
their activity state. At most 48 waveform bars are drawn. Worker threads publish
only a scalar level and phase; the GUI receives no recording buffer. Reply
amplitude uses a compact 100 ms RMS envelope timed to the owned audio player,
not acoustic monitoring of the speakers. This is turn-taking voice chat, not
simultaneous interruption/barge-in.

## Compact voice views

Hands-free adds a temporary voice view to each existing compact mode. In collapsed
Compact, the proxy entry/Attach row is replaced by the voice panel. In expanded
Compact, that same voice panel accompanies the existing full transcript, including
your transcriptions, Nice's text replies and earlier history. The existing toolbar,
Expand/Collapse, Full UI and Stop remain available, with Mute and End hands-free
on the voice card. Normal compact layout, entry contents and attachment controls
return when hands-free ends or fails. Switching layouts keeps the same voice
session and transcript; only one visualizer timer runs. The full-size voice card
has its own row outside the transcript, so decorative branding stays behind chat.
ControlCenter/voice_layout.py contains the adapter; normal compact behaviour stays
in portal_frontend_v15136.py.

## Source and verification

Memory coordination: Agent/voice_memory.py, media_policy.py, tts_policy.py,
stt_bridge.py, stt_worker.py, piper_bridge.py and piper_worker.py. GUI integration:
ControlCenter/chat_voice.py, native_chat.py, voice_activity.py, voice_visualizer.py,
voice_logo.py and voice_layout.py. Agent/nice_voice.py owns expressive voice workers.
Regression coverage: Maintenance/Tests/test_voice_memory.py,
test_voice_visualizer.py, test_voice_layout.py, test_nice_voice.py, test_chat_voice.py
and the existing handoff/Stop suites.
Tools/smoke_voice.py includes the new module in its relocated-runtime fixture.
Public release validation records actual test counts, live checks and measured
GUI performance. Tests use marked synthetic roots and generated speech; they do
not inspect owner chats or establish physical microphone/human audibility proof.

Exit and reopen PortalAI normally to load the update. Both D and E retain
independent Full installations and SSD-local dependencies. Windows Full/Academic
preserve their edition policies and model/runtime pins. Linux/Mac remain r51.

## Nice voice preset

On a capable GPU with the existing Qwen3-TTS CustomVoice model installed, Nice
uses its Ryan speaker with the expressive instructions in Agent/nice_voice.py:
a youthful adult male, bright upper-mid register, warm and courageous delivery,
natural rhythm, varied intonation and conversational emphasis. The user reviewed
and selected a generated sample. There is no pitch filter on this voice and no
actor recording or voice cloning. Existing Qwen models and runtimes are reused.

Expressive TTS always acquires the shared GPU lease, releases only owned idle chat,
checks the unchanged Qwen RAM/VRAM floors, synthesizes and plays the answer, then
restores the exact chat model healthy. Its gated Windows job owns the worker tree,
with a 240-second deadline, 16 GiB process commit limit, bounded log and output, and Stop/
account checks throughout. Requests and partial outputs are removed on ordinary
failure/cancellation. Worker exit releases TTS allocations. Four CPU math threads
avoid excessive worker contention. GPU preparation adds latency, especially when
a large chat model must unload and reload for every voice chunk.

If installed assets or hardware cannot run Qwen TTS, the displayed basic CPU
fallback uses pinned Piper en_US-joe-medium, brightened by two semitones with the
bundled FFmpeg rubberband filter without speeding speech. A Qwen inference error
does not silently retry in another voice. Generic Piper commands retain their
original default. No extra Python runtime is installed. This approximately 60.3
MiB fallback voice is independently stored on each SSD, with its configuration
and CC0 model card. Agent/voice_assets.json records its immutable revision, URL,
size and SHA-256. The Piper worker verifies the selected model and configuration.

## Measured visualizer cost

On this Windows host, four light/dark cases at 720/1260 pixels retained 51 canvas
items, with median paint/display-flush times of 1.38–2.37 ms and 95th percentiles
of 1.75–6.29 ms. Cached logo pixels total 80,896 bytes. After 2,000 additional
frames, retained traced Python growth was 8,888 bytes; settled listening issued
zero canvas updates in 1,000 polls. These are local measurements, not guarantees
for every host or GPU workload.

## Automatic, manual and linked voice selection

Chat Preferences includes the same staged Voice model and Link voice to effort
controls on the Microphone & hands-free and Effort & continuation pages. Choices
are Automatic, Qwen TTS — expressive, and Piper — lightweight. Save persists them
per account; Cancel leaves current settings untouched. The effort bar includes
the resolved TTS model. The background hardware scan reports both models, missing
assets, RAM/VRAM requirements and Whisper Base availability; it uses total capacity
for previews and rechecks actual free memory only at execution.

Linked Automatic uses Piper for Fast and prefers Qwen for Balanced/Deep when the
installed hardware supports it. Selecting a linked manual voice synchronizes the
effort selection: Piper → Fast; Qwen → Balanced (or retains Deep). Subsequent
slider changes also update a linked manual voice. Turn Link voice to effort off
to keep a manual TTS choice independent of the LLM and slider. Unlinked Automatic
selects the best supported installed voice independently of LLM effort. A missing
or unsupported explicit model is reported, never silently replaced. All modes
retain memory/storage floors and generation-guarded restoration.

Agent/voice_policy.py owns this small capability/selection policy;
ControlCenter/voice_preferences.py owns the staged controls. No new model is
downloaded by a scan or selection. See Portable_Tasks_r55.md for the general-task
file tools added in the same Windows release.
