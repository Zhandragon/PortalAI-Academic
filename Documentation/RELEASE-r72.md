# Windows r72: logic audit and compatibility repairs

This logic-first review found seven functional defects/groups and removed one obsolete theme reference:

1. Automatic coding routing could reuse a partially GPU-loaded plan despite requiring the specialist to fit fully on the GPU. Cached and preview plans now obey the same admission requirement as fresh plans.
2. Science tools could raise NameError in the optional-runtime/platform error path because sys was not imported. They now return the intended structured error.
3. Tracked file writes could turn Windows CRLF endings into CRCRLF. Writes normalize line endings once; undo still restores the exact original bytes.
4. Human confirmation of an uncertain workflow step ignored its declared next destination. It now follows the saved branch, including end, without executing skipped tools.
5. Workflows treated explicit native success:false and ok:false results as success. They now retain the pending step for review, without automatic replay.
6. The updater rejected properly closed unencrypted/account-free profiles because their workspace intentionally remains readable. It now verifies public account policy, closure identity, recovery blobs and current file hashes. Pending recovery, changed files and plaintext left under encrypted policy still block the update. The Windows installer embeds the repaired engine.
7. Plaintext recovery and privacy conversion had hardcoded 80 GiB checks that bypassed the configured SSD reserve. They now use the shared policy, including the user's 50 GiB setting. Default policy and research-specific limits are unchanged.

The obsolete exit_menu theme block referenced a nonexistent variable and silently swallowed the exception. Removing it leaves the existing themed menus and layout intact.

Validation uses source-wide syntax/name/call-shape analysis, manual review of critical dispatch, model admission, workflow recovery, persistence, privacy, voice cleanup, retrieval and installer paths, and focused disposable regression fixtures. Confirmed failures were reproduced before their fixes. The audit report lists coverage and passing checks; this is not a claim that every possible bug has been excluded. Vendored dependencies and the deprecated C installation are outside this pass.

No model benchmarks or new LLM/TTS inference are run. No dependencies, model weights, account formats or user preferences are added or migrated. D/E remain independent, paused weight research remains paused, and the release preserves historical upgrade compatibility. Linux/Mac packages remain at their existing published revision. Normal PortalAI restart activates code already loaded by an existing process.
