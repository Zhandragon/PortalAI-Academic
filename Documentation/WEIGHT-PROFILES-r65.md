# Reversible weight-edit profiles

PortalAI reversible weight-edit profiles — Windows r65

Original standard and uncensored model files remain intact. A profile applies
only to its exact model checksum and quantization; the standard and uncensored
variants need separate profiles. A different selected model keeps its own
original weights. No profile is selected automatically.

1. Open Controls > Utilities > Weight-Space Editor. Choose the original model,
   a tested candidate and its edit recipe. Save candidate as profile stores an
   exact compressed .wsedit patch under LLM/WeightEdits/Profiles.
2. Choose the saved profile and Prepare selected. This creates and fully hashes
   a loadable candidate under LLM/WeightEdits/Prepared. Preparation requires an
   idle GPU lease so cache removal cannot race a model switch. Nothing is loaded
   by preparation itself. Existing application accounts are not changed.
3. In Settings > Chat models choose Weight edit profile and Save. It applies on
   the next request, through the existing idle/ownership/Stop-aware model switch.
   Select Original weights and Save to revert. Both choices are per account.
   A ready cached profile avoids rebuilding weights; switching still unloads
   and reloads the model and is not instantaneous.

Profiles are explicitly experimental. They can help a particular task while
worsening another. No automatic profile retry or uncertain tool replay is
enabled. After changing profiles, a task can continue using the existing saved
conversation/checkpoint and pending-action review rules. A profile cannot add
knowledge or abilities absent from the underlying model by guarantee.

Storage: the library contains only changed 64 KiB pages, with before/after
checksums, recipe and receipt. The first 1.7B experiment is a 25,783,118-byte
patch versus a 1,834,426,016-byte model. A prepared copy still needs the full
model size. At most two prepared copies are retained; an oldest unused copy
may be evicted only after the replacement passes its complete checksum.
Staging a third copy and all operations preserve at least 80 GiB free.
Clear prepared copy removes only an unchanged, unloaded derived candidate and
its certificate. It retains originals and compact patches. Interrupted or
unfamiliar cache contents are preserved for review, never silently deleted.

The GUI reads bounded small sidecars; it does not hash gigabytes on Tk's event
thread. Copying, patching and full hash verification run in an owned worker.
Preparation certificates use file identities/timestamps to detect ordinary
changes quickly; they do not defend against a malicious filesystem owner.
These shared model assets and utility artifacts are outside encrypted account
workspaces. Do not place private prompt data in profile labels/recipes.

Both D and E keep independent profiles and prepare their own copies. No new
model download, Python tree, inference runtime or resident service is added.
Windows installers preserve r64 and all earlier supported upgrade histories.
Linux/macOS distribution versions remain unchanged.

Source: Agent/weight_edit_profiles.py; Tools/WeightSpace/edit_profiles.py;
Tools/WeightSpace/{ui,utility_worker}.py; Agent/{runtime_policy,model_preferences,
effort_policy}.py; ControlCenter/settings_page.py; regression coverage in
Maintenance/Tests/test_weight_edit_profiles.py. The underlying subtraction
method and its limits remain documented in Weight_Space_Editor_r64.txt.

Study status: the first standard 1.7B discovery candidate scored 18/28, tied
with the original, with three rescues and three regressions. It is not an
accepted general improvement. Other paired model experiments are ongoing.
No production default weights are replaced by this utility release.

[Original utility and method](WEIGHT-SPACE-r64.md) · [Profile implementation](../ApplicationSources/Windows/PortalAI/Tools/WeightSpace/edit_profiles.py) · [Model routing](../ApplicationSources/Windows/PortalAI/Agent/weight_edit_profiles.py).
