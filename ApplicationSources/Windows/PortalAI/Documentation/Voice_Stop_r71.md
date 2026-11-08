# Windows r71: voice stop and component cleanup

Stopping hands-free now revokes capture immediately and performs blocking audio cleanup on a tracked worker. The GUI remains available during the return from voice to the chat model. A new voice session waits until the preceding microphone cleanup finishes.

Windows echo capture serializes repeated close calls. WinMM capture protects native buffer reads/requeues from concurrent reset and close. Stop All uses verified process handles and creation times, preserves GUI/controller ancestors, and explicitly includes voice capture and playback workers. Stop requests and results are recorded in account-aware diagnostics.

The reported incident closed the entire window after End hands-free followed by Stop All during restoration. Its empty crash log does not establish a unique cause. These changes correct independently verified cleanup races and unsafe process-tree termination. The exact original full-window exit was not reproduced, so this release does not attribute it conclusively to Swift routing.

Validation covers delayed restoration and GUI responsiveness, concurrent native audio teardown, control/settings save and cancel behavior, effort/model routing, persistence, diagnostics, and shutdown ownership. Independent D/E probes use real Windows AEC capture and the actual Stop All helper with a disposable worker and the real restoration-wait code. They load no language or speech model and open no production account. Each GUI remained alive, capture closed, the worker exited, and restoration was cancelled by Stop All. These tests supplement the r70 actual model handoffs; they are not a new full Qwen speech synthesis benchmark.

General model choice, automatic coding routing, chat history, voice preferences, optional privacy, and user storage reserves retain their existing behavior. Full retains optional Swift; Academic retains its standard-only policy. The update keeps historical upgrade compatibility. No model weights, new dependencies, or research inputs are added or changed.
