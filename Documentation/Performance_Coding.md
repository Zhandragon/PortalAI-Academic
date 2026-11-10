# Performance-conscious coding in Nice

Nice now receives a compact `perf-critical` coding rule for detected code-change
requests. You can also explicitly prefix a request with `perf-critical:` or
`[perf-critical]`. It is workflow guidance, not a special commit type or permission.

The rule asks Nice to pick a concrete acceptance check, inspect relevant source,
and take the next useful step rather than repeat plans. For requested optimization,
it calls for a baseline, correctness checks, and comparable measurements over
representative input sizes (for example n, 2n and 4n), with bounded repetitions and
timeouts. Timings alone do not prove Big-O complexity; that needs code analysis.
Routine edits do not automatically require a benchmark.

After the requested checks pass, Nice should finish. Relevant changes, failures,
or new evidence justify another check; unchanged evidence should be reused.
Unavailable tests and unmeasured claims must be reported honestly.

This guidance reads recent human requests only. It does not read attached files,
load models, select tools, grant commands, write commits, change existing budgets,
or bypass account/Stop/replay protections. It reaches legacy and progressive native
Chat prompts and maintenance mode. Existing mission-worker prompts are unchanged.

Validation covers intent scoping, prompt delivery, and the existing progress,
checkpoint and no-replay guards. This is not a measured reduction in 27B Q4
deliberation or looping; a controlled real-model comparison remains separate.

The source change is shared by Full and Academic on Windows, macOS and Linux.
macOS/Linux support remains experimental. The existing published r75 installers
retain their published hashes; this source update does not rewrite old releases.
