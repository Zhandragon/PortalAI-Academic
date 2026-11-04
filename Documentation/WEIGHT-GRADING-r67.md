# Bounded evaluation and verified cleanup

PortalAI Windows r67: code deadlines and worker cleanup

A generated program that exceeds its five-second execution budget is graded
as incorrect only after the owned worker has stopped. If termination cannot
be confirmed within the separate cleanup deadline, evaluation raises an
infrastructure error and halts. It does not claim a model score or successful
cleanup. Launch errors, malformed grader output and non-code timeouts also
remain errors. This completes the bounded coding evaluation repair in r66.

Original weights, optional edit profiles, model routing and account choices
are unchanged. Select profiles or Original weights as described in
Weight_Edit_Profiles_r65.txt. Preparing a profile uses a complete model-sized
copy; the two-copy cache and 80 GiB free-space floor remain in force.

No dependency, runtime, model download or background service is added.
Windows upgrade history retains r66 and all earlier supported versions.
Linux/Mac remain r51. Restart PortalAI normally to load the code repair.

## Fresh Windows installation

Windows r67: NVIDIA runtime and Weight-Space Editor installation

In Windows setup, select "NVIDIA chat and Weight-Space Editor runtime (CUDA 12.4)" for NVIDIA chat or native weight editing. This optional component downloads the exact official llama.cpp b10935 CUDA 12.4 engine and CUDA libraries into LLM/llamacpp. Every archive and extracted member is SHA-256 pinned. It reuses the existing core Python and Qwen speech package components for NumPy/Jinja2/SymPy; it does not create another Python environment or download additional model weights.

The two downloads total 645,506,046 bytes. Installed native files occupy 1,167,981,853 bytes. D and E already contain these exact native files, so their installed runtime is unchanged. CPU/Vulkan components remain available without selecting NVIDIA support. The editor's current native execution/research backend is Windows NVIDIA; this does not claim Radeon editing support.

Existing component pins and historical upgrade contracts are retained. Setup verifies destination conflicts, selected-component dependencies, storage headroom, and member hashes. The editor independently checks its native ABI; replacing DLLs with unrelated llama.cpp builds is unsupported. The exact source manifest is InstallerSources/Windows/weight_space_cuda_component.json in either repository.

Validation extracts the new component from the verified upstream archives and checks its ABI, DLL loading and CPU quantization without borrowing native DLLs from a live installation. This is component validation, not a complete clean-machine installation or an additional GPU inference test.
