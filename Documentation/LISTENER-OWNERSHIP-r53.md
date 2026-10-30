# Windows r53: model listener ownership repair

Typed chat and hands-free both prepare Nice's model before inference. A model
already listening could be rejected as outside the portable root because the
netstat LISTENING-text filter omitted it on this Windows host. A real bound socket
was absent from netstat, while GetExtendedTcpTable's listener-only table returned
its correct PID with an unrecognized raw state. A separate snapshot/probe startup
race could produce the same empty-owner result.

Agent/windows_tcp.py now queries the Windows IPv4 and IPv6 listener-only owner
tables directly using standard-library ctypes. It handles table growth with
bounded retries and rejects failed or malformed queries. Agent/service_manager.py
rechecks ownership after a socket opens between snapshots and requires every
listener to belong to this root. Agent/chat_model_switch.py distinguishes unknown
ownership from a positively rejected process. Port occupancy alone never grants
ownership; executable path, model identity, readiness and Stop fences remain.

The current Mic path runs CPU Whisper directly through ControlCenter/chat_voice.py;
it does not need port 8080 and does not stop Nice. Hands-free subsequently sends the
transcript through the same model preparation as typed chat. This fix changes that
shared model path, preserving r52's visible text plus spoken replies.

Exit PortalAI normally and reopen it to load all updated modules, then use Startup
or send a message. The two SSD installations keep independent roots and runtimes.
Do not kill another installation's server merely because it occupies a port.

Regression source: Maintenance/Tests/test_listener_startup.py and test_windows_tcp.py.
These cover late binding, missing PID data, mixed/foreign ownership, failed native
queries, and actual Windows IPv4/IPv6 sockets and established-only connections.
See Documentation/LISTENER-VALIDATION-r53.json in GitHub for final test receipts
and live-test limitations. Linux/Mac distributions remain r51; Windows includes r52.

Native API reference:
https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
