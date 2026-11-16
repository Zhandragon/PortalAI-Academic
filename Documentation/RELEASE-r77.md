# Windows r77: handsfree stop and composer recovery

Ending handsfree now cancels its active reply promptly. Voice interruption stops
the reply while keeping listening enabled. Stop schedules HTTP and tool cleanup
in an owned background worker, and restores Send after pending loads are cleared.
Follow-ups can be queued during cleanup; explicit Stop pauses the queue until
the user resumes it. Late completion events cannot unlock a different request.

Full, Academic and the 72-hour Full Trial Windows installers carry this fix.
Academic model restrictions, trial expiry/paid-install protections, dependency
pins, optional onboarding and account sealing remain in place. Existing Mac and
Linux releases remain r75; their separate voice implementation is unchanged.

Validation: nine headless thread/socket regression tests per Windows source
edition. The original fix also passed 162 related checks with one skip. Release
archives and every payload member are checked against SHA-256 inventories;
minimum and full component plans are validated without running installer GUIs.
Physical microphone, live model/GPU latency and a fresh recipient installation
have not been tested for this release.
