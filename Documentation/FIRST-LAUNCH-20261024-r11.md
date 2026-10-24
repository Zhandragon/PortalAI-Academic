# First-launch administrator setup repair (2026-10-24 r11)

A fresh installation could ask for an existing administrator even though no account had been created. The private-data inventory was treating two public runtime files as account data: the service-endpoint record created before login and the speech-package binding supplied by setup.

The corrected inventory keeps those two direct runtime files shared. First launch now offers **Create initial administrator**. Existing accounts, private prompts and nested runtime files still require the normal authenticated recovery flow when their registry is missing. No account is created automatically; users choose their own administrator name and password.

Both editions and all three operating-system packages include the fix. The temporary Aoostar mission importer remains excluded. Runtime and model download pins are unchanged.

Validation: 70 account, migration, startup-gate and public-bootstrap checks passed for each Windows edition, including seven targeted regressions. The uncorrected source failed five of those seven targeted checks. Tests used disposable accounts and exercised real password encryption and verified migration sealing. Physical Linux/macOS installation remains untested.

Existing affected E: installations can receive the focused source repair without reinstalling or downloading models again. Close PortalAI before applying that repair, then reopen it and create the first administrator.
