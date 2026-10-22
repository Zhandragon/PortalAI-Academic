RETIRED LAN PROTOTYPE — October 12, 2026

Use ../PortalAI-Projection/Start Projection.cmd, outside the PortalAI folder.
See ../PortalAI-Projection/README.txt for the current supported companion.

This old fixed-IP inbound bridge is stopped. Launchers, pairing CLI and firewall
installer are disabled. Generated unused pairing keys and transfer ZIPs were
removed; no keys were installed on Home Assistant. No firewall rule was added.
The Python classes remain only for historical disposable regression fixtures.

Do not delete HomeAssistant/state/forced-stop.json if present: the main PortalAI
mission and schedule readers use it to prevent resumption after a forced stop.
Do not restore an old source snapshot selectively across those lifecycle readers.
