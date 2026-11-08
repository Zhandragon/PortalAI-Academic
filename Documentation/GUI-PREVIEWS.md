# Explore PortalAI's interface

These are captures of real Windows GUI widgets. They are interface previews, not new claims of completed inference. Most use a disposable, offline capture fixture with background services disabled. Voice activity is illustrative. The science file cards replay files from the documented real Nice runs. Account fields are synthetic; no private account data is shown.

The main tabs separate navigation from work inside each tab. Runtime and Models are distinct; Maintenance is independent of Help. The [storefront tour](https://payhip.com/PortalAI) mirrors this organization with ordinary help links.

## Welcome and contextual help

![Welcome](assets/gui-previews/welcome.png)

![Actual right-click context menu](assets/gui-previews/welcome-context.png)

Right-click a control to find its relevant Help topic and available actions. The preview website uses normal links; it does not execute desktop commands.

## Accounts

![Accounts and local access controls](assets/gui-previews/accounts.png)

![Portable account export controls](assets/gui-previews/accounts-export.png)

Use local accounts, roles and recovery controls to manage access to your workspace. Account export provides a portable transfer path. Normal Exit seals protected workspace files; files are available while signed in. Guest is shared, and local account encryption is not isolation from the signed-in operating-system user.

## Chat preferences

Chat combines conversation, files and tool results. Its preferences have five subtabs:

![Display preferences](assets/gui-previews/chat-display.png)

**Display:** adjust the reading and presentation experience.

![Microphone preferences](assets/gui-previews/chat-microphone.png)

**Microphone:** choose capture and voice-input settings.

![Chat effort preferences](assets/gui-previews/chat-effort.png)

**Effort:** control the reasoning budget and response effort supported by the selected model.

![Reply and memory preferences](assets/gui-previews/chat-reply-memory.png)

**Reply & memory:** tune response behavior and conversation-memory handling.

![Tools and limits preferences](assets/gui-previews/chat-tools-limits.png)

**Tools & limits:** bound work and configure supported recovery aids. r74 also lets you queue a follow-up during inference, edit/remove the next message, or choose Send now to stop the current response and send next after cleanup. Pending messages stay in the current chat only; switching chats/accounts or closing clears them.

## Science output in Chat

![Real generated files shown in Chat](assets/gui-previews/chat-science-output-cards.png)

Use **Open** on returned file cards to view generated HTML, SVG or other outputs. These are output viewers, not extra built-in science tabs. [Actual inputs, outputs and scientific limitations](science-examples/README.md).

## Runtime, Models and Packages

The package inventory captures are from Full. Academic has its own restricted model and asset catalogue.

Runtime shows host activity and resource use. Models controls model-service choices. Packages lists available capabilities and installed assets. These are separate areas of the GUI.

![Packages capability inventory](assets/gui-previews/packages.png)

![Package weight inventory](assets/gui-previews/package-weights.png)

## Settings

**Edition disclosure:** the three subtab captures below show Full UI controls. Academic enforces its standard-model policy and excludes abliterated options and the abliterated coding specialist; those Full-only controls are not Academic features. The Academic settings capture in the feature tour shows the restricted edition.

![Chat settings](assets/gui-previews/settings-chat.png)

![Media settings](assets/gui-previews/settings-media.png)

![Web and agent settings](assets/gui-previews/settings-web-agents.png)

Choose chat/media policy, supported backends and web/agent preferences. Hardware admission checks still apply. Full and Academic have different model policies.

## Persistence

![Mission controls](assets/gui-previews/persistence-missions.png)

![Schedule controls](assets/gui-previews/persistence-schedules.png)

Missions retain objectives, budgets and review state. Schedules must be enabled explicitly. Saved drafts in these captures were not executed. Ongoing work needs PortalAI running, the host awake and the drive connected.

## Maintenance, Help and tray controls

![Maintenance](assets/maintenance-current.png)

![In-app Help](assets/help-current.png)

![Actual Windows tray menu](assets/gui-previews/tray-menu.png)

Maintenance groups diagnostics, storage and repair controls. Help provides searchable operating documentation. On Windows the notification menu can restore the workspace, navigate and exit. The menu image was opened in an isolated fixture; it is not a screenshot of the operating-system notification area. Minimizing does not sign out or seal the workspace.

## Donate

![Donation page](assets/gui-previews/donate.png)

The Donate control opens the application's donation options and QR codes. The storefront mirrors these at its own Donate page.

Native Mac/Linux behavior and component availability differ. Packaging checks do not replace testing on those operating systems. [Full feature tour](FEATURE-TOUR.md).


## Follow-up messages while Nice works

![Actual r74 follow-up controls](assets/gui-previews/chat-followups.png)

Queue the next message during inference, edit or remove it, or choose Send now to stop the current response and continue after cleanup. Pending messages belong to this chat and account only and are kept in memory. This screenshot shows the actual r74 controls with an illustrative conversation and queue; inference was disabled for the capture.

## Desktop shortcut

![PortalAI desktop shortcut](assets/gui-previews/desktop-shortcut.png)

Actual Windows desktop shortcut for the local PortalAI installation, cropped to the icon and label.
