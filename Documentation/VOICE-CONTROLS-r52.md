# Microphone and hands-free voice (Windows r52)

Mic records dictation. Click Stop Mic to transcribe into the message draft, review it,
and Send when ready. Hands-free captures an utterance, transcribes it, sends it to
Nice, displays the normal text answer, speaks the completed answer, and listens again.
Enable **Speak Nice's replies** in Chat Preferences > Microphone & hands-free
(enabled by default). End hands-free or Stop cancels capture, transcription and speech.
Switching conversations, signing out and closing the app also revoke pending voice work.
Restart PortalAI normally after updating an already open application.

Replies use the bundled offline English Piper CPU voice. STT uses the portable
Whisper runtime on CPU, with its existing memory-admission checks. Neither path
needs host Python or a cloud account. They do not unload the conversational model.
Hands-free is turn-taking, not full-duplex: it pauses submission during the reply
and drains old microphone buffers before listening again. Voice interruption by
speaking over Nice and wake-word activation are not implemented. Code blocks are
described as being in the chat; Markdown is simplified only for speech. Long replies
are spoken in bounded chunks. The original text remains unchanged. Temporary reply
WAVs are removed after playback or cancellation.

## Missing transcription runtime repair

The reported failure occurred on both installations when Agent/.runtime/stt_runtime.json
was absent even though SpeechToText/python_packages and Runtime/BootstrapPython worked.
The bridge now validates the cached portable paths and resolves installed local
packages automatically when that binding is absent, corrupt, stale or external.
Binding writes are atomic. This recovery does not download packages or restore the
removed Qwen Python tree. STT and Qwen TTS are separate runtime layers.

If required packages are genuinely unavailable, the error points to the diagnostic
binding and explicit repair command. Use this installation's bundled Python:
`Runtime\BootstrapPython\python.exe Tools\stt_runtime.py --root . --repair`.
Automatic microphone recovery does not run this installation/download repair.

## Source map

- ControlCenter/chat_voice.py: turn ownership, transcript selection, speech chunking,
  cancellable STT/TTS/playback and temporary output cleanup.
- ControlCenter/native_chat.py: microphone controls, hands-free loop, preferences,
  visible answer delivery and cancellation/account/conversation fences.
- Agent/stt_bridge.py and Tools/stt_runtime.py: portable discovery and owned STT worker.
- Agent/piper_bridge.py: owned CPU speech worker and cancellation callback.
- Maintenance/Tests/test_chat_voice.py: recovery and native Tk event-loop regressions.

All listed files are individually published under ApplicationSources/Windows/PortalAI.

## Validation and limits

On each SSD, 188 focused tests completed: 187 passed and one existing Windows symlink
fixture skipped. Coverage includes two successive native Tk hands-free turns, visible
answers, draft-only dictation, stale events, failed admission, Stop, writer shutdown,
TTS policy and CLI. Synthetic model/microphone doubles were used for the Tk loop.

Separate isolated fixtures on D and E used each drive's real portable runtime for
offline Piper speech, Whisper transcription, ffplay audio-device playback and output
cleanup. Both produced non-silent speech and recognized the test phrase, with a minor
recognition error at the start. Real worker cancellation was verified during STT,
TTS and playback; owned children exited and no extra output remained. Existing voice
smoke tests also verified cancellation and parent-crash worker termination on both.
These checks did not capture a person's physical microphone, establish perceived
speaker loudness, or exercise a live model-generated hands-free conversation.

Windows r52 installers incorporate the previously published mission recovery,
Workspace, integration and Qwen runtime corrections plus this voice repair. Their
public Workspace runtime is included. Full and Academic retain their own policy.
Linux and Mac remain on r51; this release does not claim their voice validation.
