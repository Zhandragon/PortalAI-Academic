PortalAI Projection Host Update 0.5.13

This companion update pairs with Home Assistant 0.5.13. It applies to both
Full and Academic editions; it changes no models, accounts or tool grants.
Stop Projection normally. Using its bundled Python, run:
  python install_host.py /path/to/PortalAI-Projection --projection-stopped
Windows example when this folder is beside PortalAI-Projection:
  ..\PortalAI-Projection\Runtime\Python\python.exe -I install_host.py ..\PortalAI-Projection --projection-stopped
Linux: use Runtime/LinuxPython/run-python. macOS: use the matching bundled
Runtime/MacPython-<architecture>/bin/python3.12.
The installer checks the exact known source hash, verifies a recovery ZIP,
then installs only app/portalai_target.py and app/native_handoff.py atomically.
It refuses differing/newer source instead of overwriting it. Preserve
Connections/ and state/. Start Projection normally after installation.
No automatic sign-in, pairing, command replay or PortalAI chat is performed.
To roll back while Projection is stopped, restore the original app source
from the reported Recovery ZIP; the unused helper may remain in place.

Completed native remote operations hand off after two seconds. Commands still
in flight remain protected, uncertain outcomes retain the existing bounded
fallback, and legacy screenshot-viewer leases remain unchanged. Desktop-only
use and idle/background/read-only operation do not acquire this native hold.
Synthetic tests pass. Native Linux/macOS execution remains unverified.
