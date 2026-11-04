# Optional experimental weight-edit profiles

These are manually selectable tradeoffs, not accepted general upgrades. No original model is replaced or automatically deselected.

| Model | Original | Edited | Optional download |
|---|---:|---:|---|
| 1.7-standard | 18/28 | 18/28 | [Profile ZIP](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.04-Desktop-r65/PortalAI-Experimental-Edit-1.7-standard-r65.zip) - [SHA-256](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.04-Desktop-r65/PortalAI-Experimental-Edit-1.7-standard-r65.zip.sha256) |

The scores are from small discovery sets, not independent confirmation or broad intelligence certification. Each ZIP includes the domain tradeoffs, exact original/edited checksums, model license and revert instructions.

Extract a chosen ZIP into **PortalAI Windows**, merging its LLM and Documentation folders. In Controls > Utilities > Weight-Space Editor, select the matching original model and profile, then **Prepare selected**. Choose it under Settings > Chat models > Weight edit profile and Save. Select **Original weights** and Save to revert on the next request.

Patch sizes vary by model and are recorded in the download index. Preparation needs a full-size model copy. At most two prepared copies are retained, with an 80 GiB free-space reserve even during staging. Switching reloads the model; no completed or uncertain tool action is replayed. The checksum and variant must match exactly.

The fresh installers provide the editor and Settings controls. For native editing on NVIDIA, select the optional NVIDIA chat and Weight-Space Editor runtime in Windows r67 setup. These optional data packages are separate downloads. D/E already have independent copies of the evaluated profile library; portable archive copies are under Utilities/Installers/OptionalWeightProfiles.

[Current campaign results](RESULTS.json) - [Reproducible method and source](README.md) - [Machine-readable download index](OPTIONAL-PROFILES.json).
