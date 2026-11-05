# Final-case preparation (CPU only)

No final model benchmark has run. Independent confirmation is still running,
and original model selections are unchanged. These files prepare part of the
conditional final evaluation; they do not bypass the evidence gates.

The adapters, exact overlap screening and complete-pair scoring checks passed
19 synthetic CPU tests. Existing Parquet-to-JSON conversions were also compared
with every row of the pinned raw files using the existing portable PyArrow.
No new dependency, model download or host installation was needed.

The prepared plan contains 4,467 unique questions and 11,265 generation requests
per arm: MATH-500 (500, four repetitions), GSM8K (1,319, two), AMC23 (40, sixteen),
Minerva (272, four), OlympiadBench (674, four), MMLU-Pro (992, one), IFEval (541,
two), and the previously validated restricted MBPP subset (129, one).

A fixed hash seed selected 1,000 MMLU-Pro rows. Four overlapped the practice pool
and four repeated another selected question after case/whitespace normalization;
all eight were excluded without replacing them. Exclusions and selected IDs
are recorded. This is exact-text screening, not semantic decontamination. The
MBPP result must be called a restricted subset, never the full benchmark.

Prompts, answers, repetition counts and paired seeds are inspectable in
prepared-case-plan.json. This is a prepared case set, not the final execution
freeze: the separate bounded executor, fresh tool-use cases and actual-harness
checks remain to be implemented and tested. Positive audited confirmation is
required before any final model execution. GPQA remains unavailable, so these
artifacts do not support a claim of complete original-paper reproduction.

Final metrics reject missing or extra responses, altered plan seeds, invalid
telemetry and infrastructure errors disguised as wrong answers. Repetitions
are averaged within each question, questions equally within a dataset, and
datasets equally within a domain. Cutoffs and native generation latency are
reported. Missing domains block an overall required-domain score. Metrics alone
cannot authorize promotion or claim actual-harness validation.

The source modules originally live in Maintenance/Research/Takehi-PortalAI-20261103;
the prepared JSON is in its final-benchmarks directory. The checkpoint/publication
helpers live in Maintenance/Validation/Weight-Final-r69 and are maintainer tools.

The live checkpoint helper uses SQLite online backups without writing the
running database. It verifies saved request/payload hashes and preserves the
exact JSON response bytes, ledger and request records. Identical archives and
pinned input bundles were verified on D and E at 399 baseline cases. The input
bundle is reused by checksum. A restore must first check the current owner,
pause markers, model hashes and authoritative completed cases; an older mirror
must never roll back newer results. No automatic restore or duplicate worker
is started, and large model files are not duplicated in these snapshots.
