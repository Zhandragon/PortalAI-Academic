PortalAI Windows r82 - reliable generated-file delivery
Version: 2026.11.22-Desktop-r82

Nice now receives consistent output-path guidance before generating a program.
New account-managed files belong under Outputs/ or User Folder/. A new ambiguous
relative destination no longer falls into the shared application folder. Existing
source files, reviewed public-source folders and explicitly chosen absolute admin
destinations keep their existing access rules.

An undeclared destination rejected before writing returns a structured failure,
with write_started=false and a concrete correction. It is no longer mislabeled
as an uncertain write. Authentication, Stop, stale login, cross-account access,
resource limits and actual interrupted writes retain their existing protections.
There is no automatic retry or replay.

Tool guidance distinguishes ordinary browser files from the offline Workspace
artifact preview. That preview cannot load CDN scripts, module imports or network
assets. Nice is instructed to choose the output tool before drafting, correct a
path error without redesigning the program, verify the existing result and avoid
unnecessary duplicate artifact generation. Saving a file does not prove its
runtime behavior. These are workflow improvements, not a promise that every
model response or generated program is correct.

Windows Full, Academic and Trial retain edition rules and dependency pins.
Includes the r79-r81 voice, desktop/browser use, media planning, shutdown,
startup model-display and Runtime sampling updates. Experimental Linux/macOS
packages remain r75; no new native Unix validation is claimed.

Validation details are in VALIDATION-r82.json. Tests use disposable profiles.
The observed windmill program was not edited or included in this release.
Install using normal Exit and verified account sealing, then ordinary sign-in.
Accounts, models, outputs, credentials and saved settings must be preserved.
The Aoostar handoff requires receiving-machine review; it is not deployment.
