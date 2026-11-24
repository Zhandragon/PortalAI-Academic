# PortalAI Home Assistant 0.5.13

Phone microphone input now sends recognized speech to the currently connected
PortalAI conversation. Successful native remote commands hand off control after
two seconds. An optional PortalAI Voice integration connects an HA voice pipeline
to a dedicated, already signed-in PortalAI chat.

- Rebuilt on the newer 0.5.12 timeline source, preserving history, media,
  attachment handling, HTTP crypto and account/busy/modal checks.
- Tap-to-talk uses the phone microphone and the configured HA STT service;
  it does not record the host microphone or include pending desktop attachments.
- Active commands remain exclusive; uncertain outcomes retain a bounded fallback.
  Idle/background/read-only operation does not acquire a native control hold.
  Ordinary desktop input is not globally locked; legacy screenshot leases remain.
- Voice delivery keeps viewer demand alive while waiting for admission and reports
  uncertain outcomes without automatically sending a duplicate command.
- Household names, entity groups, aliases and assistant instructions stay in
  deployment configuration. An environment reference template is included.

Install the HA package and matching Projection Host update below. Backups and
checksum verification are built in. Keep existing encrypted connections and
pairings. Host updates refuse differing/newer source for manual reconciliation.
Add/configure the optional voice integration explicitly; installing its files
does not grant device control or change a default assistant.

Validation: 109 JavaScript checks, 104 Python receiver/installer/voice checks,
25 synthetic host checks, and an actual full-payload install/rollback pass.
The new test uses the real panel class to check speech/attachment separation and
the preserved timeline. Host installer checksum, idempotence and changed-source
rejection were also exercised. No real devices are manipulated by these tests.

Live model-driven normal-light actions have been independently verified, but
voice completion has been intermittent and may take minutes. Physical phone
microphone, Voice Preview end-to-end and native Linux/macOS acceptance are not
claimed. Test the optional voice route before selecting it as your default.
This is a full integration release, not a prerelease. Current r85 application
installers and model/runtime pins are unchanged; apply this companion update
after an existing or fresh r85 installation to obtain these integration changes.

[Download the verified HA and matching host packages](https://github.com/Zhandragon/PortalAI-Academic/releases/tag/v2026.11.24-HA-0.5.13).
