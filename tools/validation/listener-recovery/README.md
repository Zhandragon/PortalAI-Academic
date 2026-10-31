# Listener and voice live validation

These are the exact synthetic harnesses used for the Windows r53 follow-up.
Place them beside a dedicated `listener-fixture` directory under an explicitly
marked Maintenance/Validation directory. Use that fixture's bundled Python with
`-B -I`, and run the scripts sequentially. Each requires a fixture-manifest.json
declaring `no_owner_accounts`; never copy a production account or private data.

The fixture uses public Agent/ControlCenter/Tools Python source, distributed
hardware/voice metadata, the public default Agent/config.json, portable_python.cmd,
and test_chat_voice.py, test_chat_timeline.py and tk_fixture_cleanup.py under
Maintenance/Tests. Public dependencies are BootstrapPython, AccountPython packages,
the complete Windows CPU llama backend, Qwen3-4B-Q4_K_M.gguf, Whisper base and its
package layer, Piper English assets and packages, and bundled ffplay. Immutable
assets may be hardlinked on the same SSD; if that is unavailable, copy and verify
their checksums. Never share live state across D/E or instantiate an owner session.
Set the fixture's public hardware policy to explicit qwen4-q4, CPU, 8192 context
and speech_model base. Set a free dedicated qwen port in instance-settings.json.
All outputs stay in the fixture or this marked validation directory.

live_check.py covers actual startup, inference, transcription and stop/restore,
then the shipped Tools/smoke_chat_handoff.py with --case error and --effort fast.
tool_handoff_live.py reruns that final handoff separately. handsfree_live.py uses
the actual withdrawn Tk conversation loop, event pump and NativeChat worker,
with two real STT/model/TTS turns and audio-device playback. Only WAV ingress and
submission setup are synthetic; its voice-only requests disable tools/thinking.
The separate handoff smoke covers real tool execution and restoration. Its deliberately minimal media fixture returns an expected missing-checkpoint error; this is not evidence that the installed D/E media assets are missing.
manual_mic_live.py tests actual Whisper output delivered into the native draft
without submitting a message. PORTALAI_VALIDATION_EFFORT can select fast or
balanced for the handoff probe; the actual receipt records the selected effort.

The initial D no-effort harness exhausted a 700-token cap without normal GUI
context metadata. The successful handoff used actual effort preparation. This
does not certify physical microphone speech, subjective audibility, a full
recipient installation, or native Linux/macOS execution.
