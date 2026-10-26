"""Public Help catalog. No probes, private data access or runtime initialization."""
import re

CATEGORIES = ('Getting started',
 'Chat, history and vision',
 'Images, video and audio',
 'Science and automation',
 'Diagnostics and maintenance',
 'Home Assistant and recovery')

TOPIC_ALIASES = {'edit_last': 'edit',
 'persistent_memory': 'memory',
 'component_diagnostics': 'diagnostics',
 'comfyui': 'comfy',
 'acestep': 'ace',
 'qwen3_tts': 'tts'}

ACTION_TOPICS = {'Startup': 'startup',
 'System Test': 'system_test',
 'Full Component Diagnosis': 'diagnostics',
 'Full diagnosis': 'diagnostics',
 'Stop all components': 'stop',
 'Exit PortalAI': 'exit',
 'Run selected': 'diagnostics',
 'Fresh-machine readiness': 'fresh_machine',
 'Verify media stack': 'media_stack',
 'Storage Audit': 'storage',
 'Deep Duplicate Scan': 'duplicate',
 'Dependency Isolation Test': 'dependency',
 'Reference Integrity': 'reference',
 'Maintenance Reports': 'reports',
 'Safe Cleanup Plan': 'cleanup',
 'Root-only Cleanup': 'declutter',
 'Delete Web Cache': 'delete_web',
 'Delete All Outputs': 'delete_outputs',
 'Delete All Conversations + Memory': 'delete_conversations',
 'Vision Asset Checksums': 'vision_integrity'}

TOPICS = {'quick_start': {'title': 'Quick start',
                 'category': 'Getting started',
                 'aliases': ['welcome', 'help', 'documentation', 'portableai', 'portalai'],
                 'body': '1. Open PortalAI.exe and sign in normally. A fresh copy first needs account setup.\n'
                         '\n'
                         '2. In Settings, choose chat model, memory and media defaults. Chat and media '
                         'variants are separate per-account choices.\n'
                         '\n'
                         '3. Use Controls → Startup to apply chat settings, then open Chat. Media, science and '
                         'vision workers load on demand; Startup does not launch every installed model.\n'
                         '\n'
                         '4. Use System Test for a first check, then select a component in Maintenance if '
                         'something needs attention. Full diagnosis and dependency imports are broader checks; '
                         'complete model checksums are a separate, disk-intensive action.\n'
                         '\n'
                         '5. Exit normally and wait for verified account sealing before ejecting the SSD. Stop '
                         'all components cancels work but keeps the account signed in.\n'
                         '\n'
                         'Choose a category above or search all topics. Topics are alphabetical, with Quick '
                         'start pinned first. Right-click a control for its matching actions and help.'},
 'controls': {'title': 'Controls',
              'aliases': ['controls', 'startup', 'stop all', 'system test'],
              'body': 'The six primary controls remain Startup, System Test, Full Component Diagnosis, Stop '
                      'all components, Minimize to tray and Exit. Startup saves pending chat settings and '
                      'applies the selected model/backend, safely switching an idle owned model. Controls '
                      'shows pending/saved choice and loaded chat separately. Stop cancels active chat, pauses '
                      'armed missions, invalidates model restoration and stops only this root’s workers. It '
                      'preserves unrelated listeners. Exit performs managed shutdown; minimizing leaves work '
                      'running. Settings holds model/media policy; Persistence holds missions and schedules.',
              'category': 'Getting started'},
 'chat': {'title': 'Chat',
          'aliases': ['chat', 'portableai chat', 'send', 'qwen'],
          'body': 'Chat is the primary frontend. The current conversation remains raw in Data\\Chat\\Sessions '
                  'while context management, persistent memory, and tool calls are added only when needed. '
                  'Right-click the transcript for quick actions such as Copy, Edit last, Branch, and Help.',
          'category': 'Chat, history and vision'},
 'history': {'title': 'History',
             'aliases': ['history', 'rename', 'delete', 'new chat'],
             'body': 'History is the first action beside Edit last in the chat toolbar. It shows or hides the '
                     'history panel. History contains persistent local chat sessions. Selecting a session '
                     'loads it without deleting or re-summarizing the raw JSON. Two independent memory '
                     'controls are available for the highlighted/current session:\n'
                     '\n'
                     '• Contribute: whether this chat is allowed to teach the global persistent-memory index.\n'
                     '• Recall past: whether this chat may retrieve memories distilled from other included '
                     'conversations.\n'
                     '\n'
                     'Turning Recall past off creates an isolated conversation while leaving global memory '
                     'intact for other chats. Deleting one chat also removes memory observations sourced from '
                     'that chat; other chats remain intact. In Home Assistant Native UI, History opens the '
                     'complete account catalog. Enter a query and tap Search to search titles and message '
                     'text; content matches may appear after title matches. Tap Open beside one chat, then '
                     'Back to chat if needed. Next chats pages older entries. Conversation tools checkboxes '
                     'select entries for memory actions; the separate Open chat button opens exactly one. '
                     'Finish or clear pending attachments before switching conversations.',
             'category': 'Chat, history and vision'},
 'memory': {'title': 'Persistent memory',
            'aliases': ['memory', 'contribute', 'recall past', 'isolated', 'persistent memory'],
            'body': 'Persistent memory stores compact source-aware facts and chat capsules under Data\\Memory. '
                    'It does not inject whole previous conversations. Retrieval is bounded by a small token '
                    'budget.\n'
                    '\n'
                    'Contribute controls whether a chat can be a source of future memory. Recall past controls '
                    'whether the current chat can consume cross-session memory. These settings are '
                    'independent: a chat can be isolated from previous memory but still contribute new '
                    "memories later, or vice versa. Clear memory preserves each chat's Contribute/Recall "
                    'controls and advances existing raw history past the cleared point so idle backfill does '
                    'not immediately recreate it; Rebuild current explicitly re-distills one chat.',
            'category': 'Chat, history and vision'},
 'branch': {'title': 'Branch',
            'aliases': ['branch', 'branch chat'],
            'body': 'Branch creates a new persistent chat from a chosen point in the current conversation. The '
                    'original conversation remains unchanged. Use this when you want to explore an alternate '
                    'direction while preserving the source thread.',
            'category': 'Chat, history and vision'},
 'edit': {'title': 'Edit last',
          'aliases': ['edit', 'edit last', 'save regenerate'],
          'body': 'Edit last changes the most recent user turn and regenerates the conversation from that '
                  'point. Context summaries that extend beyond the edited point are invalidated so stale '
                  'compacted context is not reused. Right-clicking the transcript also exposes Edit last as a '
                  'contextual action.',
          'category': 'Chat, history and vision'},
 'runtime': {'title': 'Models',
             'aliases': ['models', 'science engine', 'services', 'status'],
             'body': 'Models shows loaded chat models, service state, CPU/GPU tool activity and persistent '
                     'mission arming. Chat can use CUDA, Vulkan or CPU. Image, speech and voice profiles '
                     'recheck available RAM/VRAM after handoff. Science is CPU/RAM on demand; OpenCL/CUDA is '
                     'explicit and requires a compatible installed plugin. Vulkan chat support does not make '
                     'CUDA media run on Radeon. Installed files do not prove recipient hardware compatibility.',
             'category': 'Getting started'},
 'activity': {'title': 'Runtime',
              'aliases': ['runtime', 'activity gpu', 'gpu vram', 'activity', 'agent', 'inference'],
              'body': 'Runtime shows rolling CPU/RAM/GPU/VRAM charts, concurrent owned process counters, '
                      'declared model stages. Controls contains Control Log below its six primary buttons. CPU '
                      'is percent of total host capacity; process GPU is the busiest engine reported by '
                      'Windows WDDM. Dedicated/shared GPU allocations can overlap between processes and must '
                      'not be summed as unique physical memory. Unsupported driver counters show unavailable. '
                      'Service residency does not establish active inference. Short native chat tools log '
                      'start/return events; process sampling can miss other short-lived external commands. The '
                      'log follows new handoff records and service/model-state changes without replaying old '
                      'history or controlling processes. Charts keep at most 60 samples; the visible log is '
                      'bounded.',
              'category': 'Getting started'},
 'installed': {'title': 'Packages',
               'aliases': ['packages', 'installed', 'installed components', 'capability scan'],
               'body': 'Packages lists each Qwen model and backend, persistent missions, offline VM shell, '
                       'Piper CPU voice, SD1.5 fallback and existing multimedia/science capabilities. Not '
                       'installed is shown for optional missing models. Presence is distinct from loaded state '
                       'and successful inference. Both native-chat science and Science Workbench remain active '
                       'with separate package trees. Legacy OpenWebUI and historical payloads remain protected '
                       'pending review. Packages and Weights & LoRAs are separate subtabs. Find a package '
                       'filters capability names and detection details. The inventory uses two columns when '
                       'the window is wide enough and pages sized to the available height; Previous and Next '
                       'browse the remaining entries. Weights and LoRAs retain separate scrollable lists. No '
                       'inventory entry or detected path is removed by filtering. KiCad 9.0.2 and stock '
                       'symbols, footprints and 3D libraries are bundled for Windows and Linux. Windows CPU '
                       'SVG/BOM/STEP exports and the existing offline Linux exports were verified. KiCad '
                       'configuration, temporary files and outputs stay on this drive under the active '
                       'account.',
               'category': 'Getting started'},
 'diagnostics': {'title': 'Full Component Diagnosis',
                 'category': 'Diagnostics and maintenance',
                 'aliases': ['full diagnosis',
                             'full component diagnosis',
                             'component diagnostics',
                             'targeted diagnostics'],
                 'body': 'Checks all registered components, including small vision, Home Assistant/Projection '
                         'source, portable recovery, runtime repair, offline Demucs, CPU MusicGen, FFmpeg, '
                         'native image backends and VM support. Rows distinguish file presence, pinned-size '
                         'checks, live state, isolated imports and lightweight science checks. Missing '
                         'optional assets are reported separately from missing required code.\n'
                         '\n'
                         'It does not send chat messages, generate media, pair HA, repair packages or prove '
                         'physical GPU compatibility. Full diagnosis does not run the multi-gigabyte Vision '
                         'Asset Checksums action. Select one component when investigating a specific problem. '
                         'Current and Previous reports keep their real outcome and timestamp.'},
 'storage': {'title': 'Storage Audit and reserves',
             'category': 'Diagnostics and maintenance',
             'aliases': ['storage audit', 'storage reserves', 'output reserve'],
             'body': 'Storage Audit inventories logical folder sizes, free space, the output reserve and the '
                     'free-space floor. It does not delete anything. Storage reserves are shared settings; '
                     'saving them requires administrator access and does not save unrelated chat/media '
                     'drafts.\n'
                     '\n'
                     'Deep Duplicate Scan is a separate, more intensive content-hashing operation. Model '
                     'downloads and runtime repair must retain their reserve budgets. A USB disappearance or '
                     'delayed-write failure is a storage problem: stop heavy scans and preserve recovery '
                     'evidence.'},
 'duplicate': {'title': 'Deep Duplicate Scan',
               'aliases': ['deep duplicate scan', 'duplicate scan'],
               'body': 'Deep Duplicate Scan groups regular files of at least 1 MiB by size and a sample '
                       'filter, then verifies matches with full SHA-256. Files that change during hashing are '
                       'reported as errors. Junctions/symlinks are skipped. Hard links already share storage '
                       'and are counted separately. Duplicate content is evidence for review, never automatic '
                       'deletion permission. Logical bytes differ from physical allocation.',
               'category': 'Diagnostics and maintenance'},
 'cleanup': {'title': 'Safe Cleanup Plan',
             'aliases': ['general cleanup', 'cleanup', 'safe cleanup plan'],
             'body': 'Safe Cleanup Plan reports narrowly allowlisted first-party compiled Python caches. Apply '
                     'rechecks file identity and content metadata before removing only those bytecode files. '
                     'Model/cache/runtime trees, diagnostic results, backups and duplicate groups cannot be '
                     'removed by this engine. Passing a dependency check never authorizes deletion.',
             'category': 'Diagnostics and maintenance'},
 'declutter': {'title': 'Root-only Cleanup',
               'aliases': ['root declutter', 'root hygiene', 'root-only cleanup', 'root archive'],
               'body': 'Root-only Cleanup previews historical installer wrappers, version readmes, stale '
                       'shortcuts and superseded root reports. Apply requires matching checksums in the '
                       'verified recovery snapshot, moves files into Maintenance/Archive and records original '
                       'paths and hashes. Old installers must not be run from the archive. User images, active '
                       'instructions and uncertain dependencies are preserved.',
               'category': 'Diagnostics and maintenance'},
 'dependency': {'title': 'Dependency Isolation Test',
                'aliases': ['dependency probe', 'dependency isolation test'],
                'body': 'Runs fresh bundled interpreters with isolated Python paths and offline model-library '
                        'settings, then checks import origins. Standard covers GUI, account-crypto libraries, '
                        'foundation and both science layers. Full adds speech, voice, ComfyUI, MMAudio, '
                        'ACE-Step, MuseTalk, Windows music understanding/Demucs and a separate ROCm layer. '
                        'NVIDIA and ROCm packages are never merged.\n'
                        '\n'
                        'Imports can use substantial RAM and time; run while generation is idle. No inference, '
                        'downloads, pairing, account creation or repairs are performed. An import PASS is not '
                        'a GPU computation result or permission to delete dependencies. A retained quarantine '
                        'journal requires reviewed recovery; it is not silently cleared.',
                'category': 'Diagnostics and maintenance'},
 'reference': {'title': 'Reference Integrity',
               'aliases': ['reference audit', 'reference integrity'],
               'body': 'Reference Integrity validates active launch/report entry points, relative hardware '
                       'policy paths, optional model presence and both active science routes. '
                       'Historical/runtime/user content is flagged for review without calling it obsolete '
                       'solely because its name is old. Dynamic shell commands and all third-party internals '
                       'are outside this check’s proof.',
               'category': 'Diagnostics and maintenance'},
 'qwen': {'title': 'Qwen / llama.cpp',
          'aliases': ['qwen llama cpp', 'qwen llama.cpp', 'qwen'],
          'body': 'Settings offers installed text models and the existing 27B vision models. Separate Qwen 3 '
                  'VL 2B and 4B Standard/Abliterated image companions use Automatic image vision and effort '
                  'matching; see Image vision · 2B / 4B companions. Model/backend admission uses available '
                  'RAM/VRAM. Tools and model handoff retain the owned Stop and readiness checks.',
          'category': 'Chat, history and vision'},
 'comfy': {'title': 'ComfyUI',
           'aliases': ['comfyui', 'flux', 'wan', 'vace'],
           'body': 'ComfyUI is the on-demand graph runtime used for local image and several '
                   'video-generation/editing workflows. PortalAI manages its lifecycle and GPU handoff rather '
                   'than requiring it to remain loaded continuously. Failed jobs retain bounded node, '
                   'exception and traceback details in the saved tool result. Known host-buffer errors '
                   'identify model-weight transfer failures; they do not establish image corruption or '
                   'the underlying driver, memory or model-file cause. These diagnostics do not retry '
                   'jobs. On Windows/NVIDIA, startup also checks available Windows memory backing '
                   '(commit), which can run low even when physical RAM is free. Under pressure, '
                   'ComfyUI leaves more GPU memory free and avoids the pinned host cache; generation '
                   'may be slower. If the remaining budget is too small it reports why. Radeon, CPU '
                   'and Linux settings are unchanged. Requested frames, size and steps are preserved. '
                   'See Comfy_Commit_Aoostar_Integration_20261018.txt.',
           'category': 'Images, video and audio'},
 'ace': {'title': 'ACE-Step',
         'aliases': ['ace step', 'ace-step', 'music generation'],
         'body': 'ACE-Step is the local music-generation runtime. It is GPU-heavy and participates in '
                 "PortalAI's exclusive GPU handoff rather than running concurrently with other heavy workers. "
                 'The bounded Radeon route uses turbo weights without a 5Hz language model; an optional '
                 'language-model directory must not be faked to pass readiness. Audio duration/decoding has '
                 'the reviewed SoundFile/FFmpeg fallback. Dependencies remain pinned per runtime.',
         'category': 'Images, video and audio'},
 'tts': {'title': 'Qwen3-TTS',
         'aliases': ['qwen3 tts', 'qwen3-tts', 'tts', 'voice'],
         'body': 'Speech output selects Qwen on capable CUDA hardware after reclaiming chat memory, or Piper '
                 'English speech on CPU when appropriate. Voice cloning/design and other languages never '
                 'silently become Piper. Both are on demand. Physical Radeon and CPU-only laptop execution '
                 'still needs recipient validation.',
         'category': 'Images, video and audio'},
 'musetalk': {'title': 'MuseTalk / Dialogue',
              'aliases': ['musetalk', 'dialogue', 'lip sync', 'lip-sync'],
              'body': 'MuseTalk drives local visible-speech lip synchronization. PortalAI routes '
                      'dialogue-video jobs through it when a visible speaker needs mouth motion aligned to '
                      'audio. dialogue-video supports 0.2..120-second timelines: --duration sets the final length, '
                      '--dialogue-start places natural speech, and --motion-plan defines timed action beats. '
                      'Speech must fit without cutting or stretching. Motion and lip sync run in bounded '
                      'segments; generated quality still depends on the models. See Dialogue_Timing_20261018.txt.',
              'category': 'Images, video and audio'},
 'mmaudio': {'title': 'MMAudio / SFX',
             'aliases': ['mmaudio', 'sfx', 'foley'],
             'body': 'MMAudio generates local sound effects/foley and is invoked on demand. It uses its own '
                     'private runtime so host Python remains uninvolved. The reviewed Windows runtime uses '
                     'PyAV/FFmpeg and its pinned Torch layer; the incompatible unused TorchCodec dependency is '
                     'not required. Video conditioning needs the matching local CLIP and BigVGAN assets.',
             'category': 'Images, video and audio'},
 'science': {'title': 'Science / Engineering',
             'aliases': ['science', 'engineering', 'chemistry', 'genomics', 'cad', 'openmm'],
             'body': 'Science Workbench families: math/stats/signal; CAD/mesh; mechanical; electrical; RDKit '
                     'chemistry; genomics/SBOL; protein/OpenMM; physics. New science.extensions schemas cover Excel, '
                     'molecular alerts/SA, measured binding fits and Vina docking, local sequence specificity, '
                     'pLannotate DNA/protein annotation, cited paper excerpts, buckling/fatigue checks, support-enabled 3MF '
                     'and profile-based slicing, transistor SPICE and explicit KiCad boards, drag trajectories '
                     'and an offline 3D Physics Lab with mechanisms, buoyancy/SPH particles, heat and bounded effects. Read Documentation\\Science_Extensions_20261016.txt. '
                     'Scores and patterns are screening evidence, never experimental safety/function proof. Most '
                     'operations are CPU/RAM on demand. protein.inspect analyzes full PDB/mmCIF files and '
                     'exports sequences, chain/residue maps and missing-coordinate information. '
                     'protein.structure_variants exports explicit sequence substitutions as FASTA with a '
                     'change report; it does not rebuild structure or predict binding/PAM/activity. '
                     'ProteinMPNN protein.design is limited to a complete 8..256-residue PDB chain, <=2 MiB. '
                     'See Documentation\\Protein_Structure_Workflow_20261016.txt. '
                     'Explicit protein.minimize platform=cuda or '
                     'platform=opencl leases GPU VRAM, temporarily hands Qwen off, then restores it. See '
                     'Documentation\\Science_Workbench.md.',
             'category': 'Science and automation'},
 'physics_lab': {'title':'Physics Lab / interactive worlds',
   'aliases':['physics','physics lab','particles','springs','ropes','pulleys','liquids','thermodynamics'],
   'category':'Science and automation',
   'body':'Ask Nice to call physics.world_schema and create a physics.world scene. Open world.html from the result in a WebGL browser; no server or downloads are required. Try the built-in mechanisms, heat/buoyancy, liquid-particle and wind/fire/breakage examples. Controls place objects, apply wind/impulses, connect springs/ropes/ideal pulleys/welds, edit heat/fuel, ignite and emit visual particles. JSON exposes all parameters. Physical fluid particles use bounded SPH; smoke/flames/sparks are visual only. Heat uses lumped capacities, fire a finite energy budget and box breakage eight pre-cut pieces. These are teaching models, not CFD, combustion chemistry, material-strength or blast-damage calculations. Fixed 120 Hz physics preserves constants; rendering adapts to hardware. Pause or close the browser to stop an opened lab: PortalAI Stop cancels generation but does not control an independently opened browser file. Save setup keeps rigid states but restarts rope/fluid internal motion. See Documentation/Physics_Lab_20261016.txt and the included Physics_Lab_Demo.html.'},
 'plannotate': {'title':'DNA annotation / pLannotate',
   'aliases':['plannotate','annotation','plasmid annotation'],
   'category':'Science and automation',
   'body':'Attach a single FASTA or GenBank and ask Nice to annotate it with pLannotate. The Windows CPU route uses real BLAST/DIAMOND searches and SnapGene/FPbase/Swiss-Prot databases. It recognizes similar and partial features; Rfam/Infernal RNA-family search is not included. Standard mode searches all three databases; fast omits Swiss-Prot. Outputs are annotated GenBank, evidence CSV and a static SVG feature map in your account outputs. Open the SVG to view, or ask Nice to explain the GenBank/CSV evidence. No sequence is uploaded. Exact supplied-reference matching remains available when explicitly requested. System Test and Science/Biology diagnostics check public prerequisites without loading models or running annotation. See Documentation\\Plannotate_20261016.txt.'},
 'chat_toolbar': {'title': 'Chat toolbar diagnostics',
                  'aliases': ['collapse trace', 'hide tool trace', 'validate chat state'],
                  'body': 'Hide/Show tool trace changes trace visibility only. Validate chat state invokes '
                          "Native Chat's existing validation callback; it is not the Control Center System "
                          'Test and does not validate scientific correctness.',
                  'category': 'Chat, history and vision'},
 'tray': {'title': 'Tray icon',
          'aliases': ['tray', 'minimize to tray'],
          'body': 'The tray icon keeps PortalAI reachable while the Control Center is hidden. Its menu '
                  'contains shortcuts to Accounts, Chat, Runtime, Models, Packages, Settings, Persistence, '
                  'Maintenance, Help, Startup, System Test, reports, theme switching, Stop, and Exit. Click '
                  'outside, Escape or changing foreground apps dismisses the menu. Tray commands are queued '
                  'back to the Tk thread rather than executed from the Win32 callback thread. The titlebar '
                  'minus button minimizes to the taskbar; Minimize to tray hides the window behind its '
                  'notification icon. Neither action stops chat or the Projection connection. Windows '
                  'minimizing is queued through the native event loop to preserve Explorer file drops.',
          'category': 'Getting started'},
 'settings': {'title': 'Settings · chat and media',
              'aliases': ['settings', 'model selection', 'hardware'],
              'body': 'Settings has Chat model and memory and Media defaults subtabs, each with its own Check '
                      'hardware fit and Save settings controls. Each Save updates only its section and '
                      'preserves the other section’s unsaved edits. Controls → Startup also saves pending chat '
                      'edits and applies the chosen model/backend, switching an idle owned model safely. '
                      'Active work must finish first. Explicit model choices remain selected across effort '
                      'changes; Automatic matches current hardware using Chat models: Standard or Uncensored. '
                      'Media models is independent: Let Nice choose, Standard or Uncensored. Both are '
                      'user-toggleable and saved per account on the portable drive. New defaults prefer an '
                      'uncensored Automatic chat model and let Nice choose media per request; existing saved '
                      'chat choices remain. Controls shows pending/saved choice and actual loaded chat '
                      'separately. Media defaults apply to the next job after Save. Media dropdowns use two '
                      'columns at normal widths, with one requirements panel for the focused control; narrow '
                      'windows scroll. Automatic, fit this computer is available for every hardware category. '
                      'MusicGen Small CPU makes 1–30s instrumentals without a GPU (10 GiB free RAM, '
                      'noncommercial weights); Automatic never drops requested vocals. Separate text-to-video, '
                      'image-to-video and music controls preserve task capabilities. Final-summary images have '
                      'Minimize/Show image buttons. Hardware fit is a read-only estimate at current available '
                      'memory, not a model load or completed inference test. Changing settings discards an '
                      'older probe result. Storage reserves are saved separately in Maintenance. Persistent '
                      'missions and schedules are in Persistence. Model/backend/context/variant/media choices '
                      'are personal, restored per account, and travel on the SSD. Storage reserves and '
                      'installed assets remain shared; reserves require an administrator. Save or Startup '
                      'commits chat changes; close normally before moving the SSD. Native chat provides '
                      'generate_image, media_tool and available_tools on every model, including 4B.',
              'category': 'Getting started'},
 'chat_preferences': {'title': 'Chat Preferences',
                      'aliases': ['chat preferences', 'reply memory', 'effort continuation'],
                      'body': 'Chat Preferences is the conversation-specific sheet. Its five tabs are Reply & '
                              'memory, Tools & limits, Microphone & hands-free, Effort & continuation, and '
                              'Display & auto memory. Save settings and Cancel remain visible on every tab. '
                              'Effort changes are staged until Save and affect the next request; Cancel '
                              'discards them. The composer slider and its details button use the same effort '
                              'policy. Tools & limits sets individual tool calls per request: zero is unlimited; '
                              'a positive limit gets a final answer after the budget is reached. Effort does '
                              'not override that choice. Completed exchanges roll into working checkpoints '
                              'while exact saved history stays available; continuation reuses saved action '
                              'evidence. Nice can request a task checkpoint and continue the same active request with '
                              'a fresh cycle. Tools & limits controls checkpoints without new tool results (default '
                              'four, zero unlimited); repeated identical idle notes still stop. Checkpoints never '
                              'reset the tool-call budget. Incomplete emergency summaries use bounded excerpts of '
                              'saved notes with history references. Model context stays bounded and Stop cancels work. The gold-bordered '
                              'Save settings and Cancel controls stay fixed while you switch tabs. Gold '
                              'sliders support arrow keys; reserve fields also accept typed values and '
                              'increment arrows. Chat instructions uses a compact PortalAI guide by default at every '
                              'context size. Custom instructions and saved media preferences still apply. '
                              'Include full reference manual is an optional setting that consumes more context; '
                              'small models retain the compact guide. Known tools need no preliminary help '
                              'lookup; repeated discovery gets a syntax reminder without executing anything.',
                      'category': 'Chat, history and vision'},
 'maintenance': {'title': 'Maintenance',
                 'category': 'Diagnostics and maintenance',
                 'aliases': ['maintenance', 'targeted diagnostics'],
                 'body': 'Start with System Test, or choose one component under Targeted Diagnostics and click '
                         'Run selected. Click the selector to open the searchable alphabetical list inside '
                         'PortalAI. Select a row and choose Use selection; Cancel keeps the previous choice. '
                         'Qwen is the default component, not the only option. Choosing does not run a check. '
                         'Full diagnosis covers the complete '
                         'catalog; Fresh-machine readiness checks portability and hardware admission; Verify '
                         'media stack checks routes and installed file anchors.\n'
                         '\n'
                         'Checks and reports: Dependency Isolation Test, Reference Integrity, Storage Audit, '
                         'Deep Duplicate Scan and Maintenance Reports. Cleanup plans and Delete data are '
                         'separate labeled groups. Each destructive action keeps its existing preview and '
                         'confirmation. Storage reserves are saved independently and require administrator '
                         'access.\n'
                         '\n'
                         'Maintenance runs one GUI check at a time. Avoid full checksums and duplicate scans '
                         'during active generation or unstable storage. Stop scanning after a device '
                         'disappearance or delayed-write error; a remounted drive is not proof that pending '
                         'writes were saved.'},
 'persistence': {'title': 'Persistence · missions and access',
                 'aliases': ['persistence',
                             'persistent missions',
                             'missions',
                             'schedules',
                             'access mode',
                             'action budget'],
                 'body': 'Persistence is a main tab, with Missions and Schedules directly available. '
                         'Choose an objective, access mode and action budget, then create a mission. Creating '
                         'does not arm it. Select a mission to inspect its current state and details; use Run '
                         'until finished explicitly. Full uses current-user host access. Observe restricts '
                         'capabilities without OS isolation. VM isolates offline guest shell actions; the '
                         'model/controller stay on the host. Schedules start paused and need Enable. Missed '
                         'intervals coalesce and runs do not overlap. Stop/Exit pauses future work, and '
                         'interrupted actions need review. The host must stay awake with the drive connected. '
                         'Administration is required. New mission/schedule objective boxes are draft inputs, '
                         'not details of a selected record. Saved missions/schedules lists show existing work. '
                         'Selected details show labeled fields including access, budgets, timing, pending '
                         'actions and results, with explicit empty-state messages. The lists and details '
                         'scroll independently; narrow windows also scroll the page.',
                 'category': 'Science and automation'},
 'accounts': {'title': 'Accounts',
              'aliases': ['accounts',
                          'username',
                          'login',
                          'password',
                          'log out',
                          'change current user',
                          'export data',
                          'start fresh'],
              'body': 'The Current Account card shows your active username and role. Change current user opens '
                      'a sign-in sheet while keeping this account active. Cancel or incorrect credentials '
                      'leave it signed in. Accepted credentials stop current jobs, save and seal this account, '
                      'then load the selected account with a fresh interface. Export Data offers chat history, '
                      'outputs or both in one verified, unencrypted ZIP file. The red Start fresh action is '
                      'administrator-only: it retains authentication, the sealed inventory review, export '
                      'choice and typed reset phrase, and now requires an additional final confirmation before '
                      'deleting reviewed private data. Models and packages remain installed. Ordinary Exit '
                      'still seals the current account and closes PortalAI.',
              'category': 'Getting started'},
 'control_log': {'title': 'Control Log',
                 'aliases': ['control log', 'control center activity log'],
                 'body': 'Controls contains Control Log under the six lifecycle buttons. It reports newly '
                         'observed tool start/return events, GPU handoffs and service/model changes. Runtime '
                         'contains the live resource charts and concurrent process readout. An observed '
                         'process exit is not proof that its work succeeded.',
                 'category': 'Getting started'},
 'small_vision': {'title': 'Image vision · 2B / 4B companions',
                  'aliases': ['vision', '2b', '4b', 'image attachment', 'abliterated vision', 'small vision'],
                  'body': 'Models and Packages list Qwen 3 VL 2B Standard, 2B Abliterated, 4B Standard and 4B '
                          'Abliterated. Each needs its matching vision projector. These are image companions, '
                          'separate from the 1.7B and 4B text models. Settings → Chat model and memory → '
                          'Automatic image vision → automatic, then Save, enables effort matching. Fast uses '
                          '2B; Balanced tries 4B then 2B if memory is insufficient. Deep with Automatic may '
                          'use the existing 27B vision model first. Uncensored chooses the Abliterated pair; '
                          'it never silently substitutes Standard. The saved text choice is retained. Images '
                          'still in conversation context require vision even on later messages. An explicit '
                          'existing vision-model choice is respected. Cold model loading can delay the first '
                          'reply; do not resend an accepted request. Stop remains available. Maintenance → '
                          'Small Vision (2B / 4B) checks all eight pinned file sizes and synthetic routing. '
                          'Vision Asset Checksums reads the complete files and compares SHA-256; it can take '
                          'several minutes. System Test, Full Diagnosis and Verify media stack include the '
                          'quick check. These checks do not prove image recognition or GPU inference. For a '
                          'live check, attach a new non-private test image and send one new request, then '
                          'inspect the active model and result. HA image previews use a small JPEG without '
                          'EXIF metadata. Load original retrieves the unchanged full file for playback, '
                          'expansion or download. Uploads remain original-size with checksums; keep HA visible '
                          'until attachment admission finishes. iOS can suspend the app in the background.',
                  'category': 'Chat, history and vision'},
 'startup': {'title': 'Startup',
             'category': 'Getting started',
             'aliases': ['start components', 'start model'],
             'body': 'Saves pending chat settings and starts or adopts the selected owned chat model. Startup '
                     'can switch an idle model; finish active work first. Available RAM/VRAM, context, storage '
                     'reserves and the selected backend still govern admission. The Controls page '
                     'distinguishes saved choice, current loaded model and historical Startup status.\n'
                     '\n'
                     'The small 2B/4B image companions are loaded only when an image request needs them, '
                     'following effort and the chat Uncensored setting. Startup does not preload every image, '
                     'video, voice, music or science model. Those tools claim resources on demand and restore '
                     'chat through the existing handoff.\n'
                     '\n'
                     'Stop cancels a queued Startup. Missing dependencies or failed health checks remain '
                     'failures; an open port alone is not readiness.'},
 'stop': {'title': 'Stop all components',
          'category': 'Getting started',
          'aliases': ['stop all', 'stop components'],
          'body': 'Cancels current chat and embedded playback, cancels queued Startup, pauses missions and '
                  'schedules, invalidates delayed model restoration and stops workers owned by this PortalAI '
                  'root. This includes on-demand image, voice, music, transcription, science and VM work. '
                  'Unrelated programs and listeners are preserved.\n'
                  '\n'
                  'Stop leaves the GUI and account open. Use Startup when you want chat available again. A '
                  'failed Stop retains evidence and reports remaining owned workers. Interrupted actions may '
                  'already have had effects: review them rather than automatically repeating Send or tools.\n'
                  '\n'
                  'The separate Projection companion and HA Recovery helper have their own lifecycle. Stop all '
                  'components is not logout, safe ejection, a forced account seal or a repair for a '
                  'disconnected SSD.'},
 'exit': {'title': 'Exit PortalAI',
          'category': 'Getting started',
          'aliases': ['exit portableai', 'logout', 'safe exit'],
          'body': 'Exit normally stops admission of new work, waits for managed writers and processes, saves '
                  'and seals the active account, then closes PortalAI. Wait until closure has completed before '
                  'ejecting the drive. If sealing fails, preserve the error and recovery evidence; do not '
                  'unplug the SSD or assume the account is sealed. Minimize to tray leaves work running.'},
 'system_test': {'title': 'System Test',
                 'category': 'Diagnostics and maintenance',
                 'aliases': ['system test', 'run system test'],
                 'body': 'A first check of the portable interpreter, command registry, owned chat lifecycle, '
                         'model/backend inventory, storage reserves, current feature files and lightweight '
                         'science functions. It includes the small-vision quick check and current '
                         'runtime/utility anchors. Some device/status probes run; heavy model generation and '
                         'complete weight hashing do not.\n'
                         '\n'
                         'PASS applies only to the row described. An idle model or absent optional hardware '
                         'can be a warning. System Test does not install dependencies, launch all services, '
                         'validate account security, send HA requests or prove media inference. Use the named '
                         'targeted diagnostic next, and Dependency Isolation Test for actual library '
                         'import/origin checks.'},
 'fresh_machine': {'title': 'Fresh-machine readiness',
                   'category': 'Diagnostics and maintenance',
                   'aliases': ['fresh machine', 'fresh-machine readiness'],
                   'body': 'Checks portable runtime paths, current hardware/model admission estimates, '
                           'component anchors and optional driver visibility. It does not initialize an '
                           'account, pair Home Assistant or enable operating-system virtualization features.\n'
                           '\n'
                           'Run on the destination computer after a verified copy. Presence and admission '
                           'estimates do not prove model generation, microphone/audio devices, physical Radeon '
                           'operation or Linux KVM support. The current shareable installer documents its '
                           'supported Windows edition; do not infer a fully validated Linux installer from '
                           'Linux source files.'},
 'media_stack': {'title': 'Verify media stack',
                 'category': 'Diagnostics and maintenance',
                 'aliases': ['verify media', 'media stack verification'],
                 'body': 'Checks media command routes and public source/runtime/model anchors for vision, '
                         'native SD1.5/FLUX, ComfyUI/Wan/VACE, Qwen/Piper speech, Whisper, MuseTalk, MMAudio, '
                         'ACE-Step, CPU MusicGen, music understanding/Demucs, FFmpeg and Radeon adapters.\n'
                         '\n'
                         'This is a lightweight structural check. It does not hash all weights, import every '
                         'dependency, allocate a GPU, perform inference or play audio. Use Dependency '
                         'Isolation Test for imports and a deliberate new synthetic request for end-to-end '
                         'behavior.'},
 'reports': {'title': 'Maintenance Reports',
             'category': 'Diagnostics and maintenance',
             'aliases': ['open reports', 'reports folder', 'maintenance reports'],
             'body': 'Opens the current account’s Data/Maintenance folder. Reports preserve Current and '
                     'Previous results with timestamps and actual pass/warn/fail or unverified state. A saved '
                     'success is historical evidence, not a new check. Run again starts a fresh check. Copy to '
                     'clipboard includes the full report even when its preview is shortened.'},
 'delete_web': {'title': 'Delete Web Cache',
                'category': 'Diagnostics and maintenance',
                'aliases': ['delete web cache'],
                'body': 'Previews and then removes only the current account’s allowlisted web cache after '
                        'explicit confirmation. It does not delete installed models, runtimes, account vaults '
                        'or HA pairing keys. Cache deletion is not a login or USB repair.'},
 'delete_outputs': {'title': 'Delete All Outputs',
                    'category': 'Diagnostics and maintenance',
                    'aliases': ['delete all outputs'],
                    'body': 'Previews the current account’s managed output locations and requires explicit '
                            'confirmation. This removes generated output files, not installed model weights or '
                            'runtime packages. Export anything you need before confirming. It is separate from '
                            'Safe Cleanup Plan.'},
 'delete_conversations': {'title': 'Delete All Conversations + Memory',
                          'category': 'Diagnostics and maintenance',
                          'aliases': ['delete all conversations', 'delete conversations memory'],
                          'body': 'Previews and removes the current account’s allowlisted chat history and '
                                  'persistent memory only after confirmation. Existing account, model settings '
                                  'and missions are not a factory reset. Export wanted chats first. Deleting '
                                  'conversation records cannot undo external effects of previous actions.'},
 'vision_integrity': {'title': 'Vision Asset Checksums',
                      'category': 'Diagnostics and maintenance',
                      'aliases': ['vision checksums', 'vision asset checksums'],
                      'body': 'Explicitly reads all eight installed small-vision model/projector files and '
                              'compares their pinned sizes and SHA-256 values. This can take several minutes '
                              'and causes substantial SSD I/O. Run only on stable storage, one check at a '
                              'time. A missing, incomplete or mismatched asset must not be activated.\n'
                              '\n'
                              'For routine checks use Small Vision (2B / 4B), which checks sizes and synthetic '
                              'routing without hashing the full weights. Neither check proves image '
                              'recognition.'},
 'home_assistant': {'title': 'Home Assistant and Projection',
                    'category': 'Home Assistant and recovery',
                    'aliases': ['home assistant', 'projection', 'ha native', 'rich details', 'attachments'],
                    'body': 'The portable Projection companion is under Utilities/PortalAI-Projection. Unlock '
                            'its saved connection, Start projection, then open PortalAI locally and sign in '
                            'normally. The companion owns the encrypted destination and device key; HA '
                            'passwords and administrator tokens do not belong in PortalAI or on the SSD.\n'
                            '\n'
                            'HA Native 0.5.11 supports account-scoped History, attachment upload, '
                            'pending-attachment Send, rich media previews and reconnect recovery. Desktop '
                            'attachments support the chooser and drop field; iPhone uses its source menu. Wait '
                            'until the attachment is admitted, then Send once. A timeout or uncertain '
                            'admission is not permission to replay a message.\n'
                            '\n'
                            'Native controls require a ready signed-in account; blocking GUI dialogs and busy '
                            'work can temporarily prevent rich reads. Close or finish the actual dialog rather '
                            'than bypassing its guard. The separate HA installer is Utilities/PortalAI HA '
                            'Setup/Install PortalAI HA.cmd, with its files retained in Setup Files.'},
 'recovery': {'title': 'HA Recovery and login recovery',
              'category': 'Home Assistant and recovery',
              'aliases': ['start ha recovery', 'recover portalai login', 'login recovery', 'portable recovery'],
              'body': 'Start HA Recovery.cmd opens the separate portable recovery helper. Remote recovery '
                      'requires its own approved pairing and explicit arming; it is independent of the normal '
                      'Projection connection. It can help recover app crashes while Windows and the portable '
                      'drive remain available. It cannot survive disappearance of the SSD containing it, '
                      'repair USB hardware or bypass account sign-in.\n'
                      '\n'
                      'For a login failure, close PortalAI normally when possible, preserve the error and '
                      'recovery evidence, then use Launchers/Recover_PortalAI_Login.cmd. It is not a password '
                      'reset or a guarantee that damaged data can be recovered. Normal sign-in and '
                      'authenticated recovery checks remain required. Never delete a vault, registry or '
                      'recovery journal to get past an error.'},
 'runtime_repair': {'title': 'Runtime repair',
                    'category': 'Home Assistant and recovery',
                    'aliases': ['account runtime repair', 'radeon repair', 'portable pip'],
                    'body': 'Runtime repair rebuilds a reviewed public dependency layer from pinned local '
                            'wheels. It is separate from diagnostics: no diagnostic button automatically '
                            'installs packages or resets accounts.\n'
                            '\n'
                            'Launchers/Repair_Account_Runtime.cmd requires the owned app closed and an '
                            'existing account installation; it repairs crypto dependencies without changing '
                            'passwords or account data. The Windows Radeon repair also uses an isolated '
                            'package layer, verified wheelhouse and checked recovery. Both use the portable '
                            'pip runner for relocated/long paths. Retain interrupted stages for review. Do not '
                            'run repairs on a disconnecting drive or treat an incomplete download as '
                            'installed.'},
 'portable_installer': {'title': 'Portable installer and moving the SSD',
                        'category': 'Home Assistant and recovery',
                        'aliases': ['clean installer', 'portable installation', 'moving ssd', 'upgrade'],
                        'body': 'Utilities/PortalAI Clean Installer contains the shareable complete installer. '
                                'Recipients use its public source/utilities and pinned upstream downloads for '
                                'large assets; no private SSD, LAN, owner account or HA pairing state is '
                                'required. Keep the package files together and follow its Windows support '
                                'instructions.\n'
                                '\n'
                                'Upgrade application files with verified recovery copies and preserve personal '
                                'settings. Do not copy Private, account workspaces/vaults, connection keys or '
                                'current projection state to a fresh recipient. A normal Exit and completed '
                                'seal are required before safely ejecting an active installation. Physical '
                                'storage reliability and recipient hardware checks remain separate from '
                                'package verification.'},
 'user_files': {'title': 'User files and encrypted profiles',
                'category': 'Home Assistant and recovery',
                'aliases': ['user files', 'user folder', 'vault', 'encrypted profiles'],
                'body': 'Signed-in files belong under Private/Users/<account ID>/Workspace. User Folder '
                        'contains personal files, Outputs holds generated results and Data holds chat/history '
                        'and other account state. The sibling Vault contains authenticated encrypted '
                        'generations.\n'
                        '\n'
                        'Lazy folders may not be materialized until PortalAI opens the requested content; '
                        'browsing an empty folder does not prove data is missing. Export through Accounts when '
                        'you need a portable readable copy. Exit waits for sealing. An active plaintext '
                        'workspace is application privacy, not operating-system isolation.'},
 'demucs': {'title': 'Demucs and music understanding',
            'category': 'Images, video and audio',
            'aliases': ['demucs', 'music understanding', 'moss', 'clap', 'separate vocals'],
            'body': 'Music understanding includes MOSS, CLAP and offline Demucs vocal separation. Each '
                    'specialist has its own model and memory requirements. Windows Demucs uses the pinned '
                    'local safetensors model and bounded complete input; it does not fetch weights during '
                    'inference. Full Dependency Isolation Test checks the music runtime imports.\n'
                    '\n'
                    'FFmpeg/SoundFile provide audio decoding where applicable. Optional model absence should '
                    'be reported honestly rather than substituted silently. The current receipt and file '
                    'checks do not prove every specialist model has run on this computer.'},
 'musicgen': {'title': 'MusicGen CPU',
              'category': 'Images, video and audio',
              'aliases': ['musicgen', 'cpu music'],
              'body': 'MusicGen Small provides 1–30 second instrumental music on CPU, with a 10 GiB free-RAM '
                      'admission floor and bounded worker. It cannot supply requested vocals. Automatic '
                      'selection must preserve task requirements and may choose this route only before '
                      'generation begins.\n'
                      '\n'
                      'It uses local public model assets and the CPU package layer, releases owned chat memory '
                      'when needed, and preserves Stop/profile guards. Its weights have noncommercial '
                      'licensing; see the shipped model notice.'},
 'ffmpeg': {'title': 'FFmpeg and media tools',
            'category': 'Images, video and audio',
            'aliases': ['ffmpeg', 'ffprobe', 'media tools', 'media editing'],
            'body': 'Bundled FFmpeg and FFprobe support media inspection, conversion, previews and audio '
                    'decoding. These deterministic tools are separate from generative models. Reports check '
                    'the portable binary paths; successful presence alone does not prove encoding or '
                    'playback.\n'
                    '\n'
                    'Outputs remain in the active account, and cancellation/profile checks still apply during '
                    'postprocessing and publication.'},
 'native_image': {'title': 'Native SD1.5 and FLUX',
                  'category': 'Images, video and audio',
                  'aliases': ['native image', 'sd1.5', 'dreamshaper', 'native flux', 'klein'],
                  'body': 'Native CPU/Vulkan image paths use stable-diffusion.cpp and pinned model components. '
                          'Standard SD1.5 and DreamShaper remain distinct choices; FLUX Klein needs its '
                          'matching encoder and VAE. Uncensored and Standard selections must follow compatible '
                          'assets rather than silently substitute another model family.\n'
                          '\n'
                          'Admission rechecks memory after chat handoff. Vulkan chat support does not make '
                          'CUDA media libraries compatible with Radeon. Presence, checksum and device-list '
                          'checks are separate from image generation.'},
 'radeon': {'title': 'Radeon media support',
            'category': 'Images, video and audio',
            'aliases': ['radeon', 'rocm', 'amd media'],
            'body': 'Radeon uses the isolated Python 3.12 ROCm package layer plus reviewed audio/music extras. '
                    'NVIDIA runtimes keep their own Torch versions. Imports and CPU fixtures establish '
                    'software compatibility only; actual Radeon compute and per-tool generation still need '
                    'physical hardware validation.\n'
                    '\n'
                    'Music uses the bounded no-LM ACE-Step route with its task limits. Instruction editing and '
                    'VACE require their own public model components and compatible memory/device admission. No '
                    'maintenance action silently replaces an explicit GPU request with CPU.'},
 'vm': {'title': 'Offline VM and access modes',
        'category': 'Science and automation',
        'aliases': ['vm', 'secure vm', 'whpx', 'virtualization'],
        'body': 'Secure VM shell actions require hardware virtualization: WHPX on Windows or the supported '
                'KVM/cgroup setup on Linux. Networking and host directory mounts remain disabled. Guest '
                'workspace archives are opaque data and are never extracted or executed on the host.\n'
                '\n'
                'The model/controller run on the host. Full uses current-user host access; Observe limits '
                'capabilities and is not OS isolation. Diagnostics inspect the VM payload and source without '
                'enabling OS features or booting a guest. Explicit VM tests must never fall back to a host '
                'shell or TCG under a secure-VM label.'}}

def canonical_topic(key):
    return TOPIC_ALIASES.get(key, key)

def filtered_topic_keys(query='', category='All topics'):
    words=set(re.findall(r'\w+', str(query).casefold()))
    result=[]
    for key,rec in TOPICS.items():
        if category!='All topics' and rec['category']!=category:continue
        hay=' '.join([rec['title'],rec['category'],*rec.get('aliases',()),rec['body']]).casefold()
        if all(word in hay for word in words):result.append(key)
    return sorted(result,key=lambda key:(key!='quick_start',TOPICS[key]['title'].casefold(),key))

def action_topic(text):
    text=str(text).casefold()
    for label,key in sorted(ACTION_TOPICS.items(),key=lambda item:len(item[0]),reverse=True):
        if label.casefold() in text:return key
    return None

from academic_policy import NOTICE as _ACADEMIC_NOTICE
TOPICS['academic'] = {'title': 'PortalAI Academic', 'category': 'Getting started', 'aliases': ['academic', 'uncensored', 'censored', 'chat variant', 'media models'], 'body': _ACADEMIC_NOTICE}
for _topic in TOPICS.values():
    if any(_word in _topic.get('body', '').lower() for _word in ('uncensored', 'variant')):
        _topic['body'] = _ACADEMIC_NOTICE + '\n\n' + _topic['body']


# Edition-specific help replaces inherited variant instructions while keeping
# the other controls' original documentation available.
_academic_help = {
    'settings': 'Chat size, backend, context budget and media profiles remain configurable. Chat variant and Media models are locked to standard; their controls do not enable alternates. Changes to backend/context still require Save or Startup. Right-click for control help.',
    'small_vision': 'Automatic image vision uses standard Qwen VL companions: 2B for Fast; 4B with a 2B fallback for Balanced. It preserves the saved text model and attachments. Install the matching standard model/projector with Academic setup. Memory admission and Stop checks still apply.',
    'native_image': 'Supported standard SD1.5 and FLUX profiles retain their existing CPU/Vulkan/CUDA hardware requirements. DreamShaper and alternate encoders are unavailable in Academic. Missing standard dependencies stop the job with an error; use the Academic import tools to install them. Standard media engines do not acquire a new output classifier.'}
for _key, _body in _academic_help.items():
    TOPICS[_key]['body'] = _ACADEMIC_NOTICE + '\n\n' + _body
