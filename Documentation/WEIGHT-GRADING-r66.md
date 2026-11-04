# Bounded weight-space coding evaluation

PortalAI Windows r66: bounded coding evaluation

The weight-space utility now scores a model-generated program that exceeds
its five-second execution limit as incorrect and continues the comparison.
The existing Windows-owned worker is stopped before the result is returned.
Launch failures, invalid grader responses and non-code grading timeouts still
raise an error; they are not silently counted as model failures.

This repair adds no runtime, dependency, model or background service. It does
not alter original weights, profiles, account preferences or model routing.
Optional edit selection and revert remain as documented in
Weight_Edit_Profiles_r65.txt. Prepared copies still require the full model size
and every operation retains the 80 GiB free-space floor.

Windows upgrade history includes r65 and all earlier supported versions.
Linux/Mac remain r51. Research results do not establish a general gain unless
the independent confirmation and final benchmarks pass.
