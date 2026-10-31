# Windows r57 — complete voice playback and a composed adult voice

Qwen's generated reply contained the complete opening word, but the user heard it clipped during a full hands-free cycle. A 500ms silent lead-in within the same playback stream fixed that reproduction, confirmed by the user. The user subsequently reported a clipped ending; a 350ms silent tail fixed the ending of the identical clip. Windows spoken replies now prime the device before speech and allow its final samples to finish before autoexit. The visualizer remains settled during silence. Stop/account guards and owned-player cleanup remain active. Padding preserves all samples from the pitch stage, without a fade or trim.

Nice's Qwen direction now targets a composed adult man around thirty, with natural conversational pacing, understated confidence and warmth. The selected voice uses a small -0.5-semitone pitch adjustment. Existing Ryan/CustomVoice weights and Piper fallback remain; no new model, dependency or resident service. Replies still appear as normal text.

Validation: 516 tests per D/E installation and exact extracted Windows edition (515 passed, one existing skip), including exact mono/stereo sample preservation and Stop during priming; 45 installer tests per edition (44 passed, one existing skip); seven embedded resources and the compiled Academic launcher. The full Whisper/4B/Qwen cycle used synthetic microphone input and actual speaker playback. The user confirmed the protected opening. Physical microphone capture, other output devices and a complete fresh recipient installation were not tested.

Both independent Full installations and local installer kits on D: and E: are updated. Windows is r57; Linux/Mac remain r51. All r56 context/tool-loading fixes are retained. Exit and reopen PortalAI normally.

[Details and source](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/VOICE-ONSET-r57.md) · [Validation](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/VOICE-ONSET-VALIDATION-r57.json).
