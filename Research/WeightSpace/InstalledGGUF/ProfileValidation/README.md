# Exact 4B profile reconstruction

The actual compact 4B standard profile was reconstructed independently on D
and E using each installation's own source and original model. The resulting
full-file SHA-256 matches the model evaluated by the discovery comparison.
Profile selection and Original weights resolution were checked in an isolated
validation root. Original file hashes were unchanged. No GPU model was loaded,
and no live account choices or prepared cache were changed. The temporary full
model and copied patch were removed only after verification.

The exact script is published alongside the receipts. It runs with the chosen
drive's BootstrapPython and `--drive D` or `--drive E`, requires that installation's
evaluated profile catalog, and deliberately refuses an existing validation
fixture. These receipts are byte reconstruction and routing evidence, not a
new inference benchmark or a fresh-machine installation test.
