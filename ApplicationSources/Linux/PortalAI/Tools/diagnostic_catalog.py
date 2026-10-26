"""Shared targeted-diagnostic names and honest, platform-neutral source coverage."""
from pathlib import Path

# The GUI and CLI must agree on both selector arguments and saved report keys.
_ENTRIES = (
    ('Qwen', 'qwen', ('qwen',)),
    ('Small Vision (2B / 4B)', 'small_vision', ('small vision','vision')),
    ('Vision Asset Checksums', 'vision_integrity', ('vision checksums',)),
    ('ComfyUI', 'comfyui', ('comfy',)),
    ('FLUX Image', 'flux', ('flux image', 'image')),
    ('Native Image', 'native_image', ('native image',)),
    ('Wan/VACE Video', 'vace', ('wan/vace video', 'wan', 'video')),
    ('Native Video', 'native_video', ('native video', 'video-small')),
    ('ACE-Step', 'ace', ('ace-step', 'acestep')),
    ('Music Understanding', 'music_understanding', ('music understanding', 'music-understanding')),
    ('Qwen3-TTS', 'tts', ('qwen3-tts',)),
    ('CPU Speech', 'cpu_speech', ('cpu speech', 'piper')),
    ('MuseTalk', 'musetalk', ()),
    ('MMAudio', 'mmaudio', ()),
    ('STT', 'stt', ()),
    ('Media Editing', 'media_editing', ('media editing', 'media')),
    ('Media Preview', 'preview', ('media preview',)),
    ('Web Tools', 'web', ('web tools',)),
    ('Science', 'science', ()),
    ('Biology Workbench', 'biology', ('plasmid', 'genomics')),
    ('Protein Design Assets', 'protein_design', ('protein design', 'proteinmpnn')),
    ('Coupled Physics', 'coupled_physics', ('coupled physics',)),
    ('KiCad', 'kicad', ('electronics',)),
    ('Radeon Adapters', 'radeon', ('rocm', 'amd')),
    ('Activity Monitoring', 'activity', ('activity monitoring', 'telemetry')),
    ('Accounts & Profiles', 'accounts', ('accounts & profiles', 'profiles')),
    ('Missions', 'missions', ()),
    ('Chat UI', 'chat_ui', ('chat ui', 'chat')),
    ('All', 'all', ()),
)
from installed_feature_checks import FEATURES, rows as feature_rows
_ENTRIES += tuple((value[0],key,()) for key,value in FEATURES.items())
CHOICES = tuple(sorted((entry[0] for entry in _ENTRIES if entry[1]!='all'),key=str.casefold)) + ('All',)
SOURCE_ONLY = {'native_image', 'native_video', 'cpu_speech', 'accounts', 'missions', 'chat_ui',
               'biology', 'protein_design', 'coupled_physics', 'kicad', 'radeon', 'activity'}
COVERAGE = ('Source, route and runtime checks only unless a row explicitly describes a live check. '
            'No media/model generation, GPU correctness, account security, VM isolation or endurance proof.')


def resolve(value):
    value = str(value or 'All').strip().lower()
    for label, argument, aliases in _ENTRIES:
        if value in (label.lower(), argument, *aliases):
            return {'label': label, 'argument': argument,
                    'report_key': 'diagnostic_' + argument, 'coverage': COVERAGE}
    raise ValueError('Unknown diagnostic component: ' + value)


def source_rows(root, component):
    """Structural checks only; never import consumers or open a user workspace."""
    key = resolve(component)['argument']
    if key in FEATURES:return feature_rows(root,key)
    paths = {
        'qwen': ('Agent/runtime_policy.py', 'Agent/chat_model_switch.py'),
        'small_vision': ('Agent/chat_vision_policy.py','Agent/small_vision_assets.json','Tools/vision_diagnostics.py'),
        'vision_integrity': ('Agent/small_vision_assets.json','Tools/vision_diagnostics.py'),
        'comfyui': ('Agent/comfy_bridge.py', 'Agent/comfy_errors.py', 'Agent/bounded_comfy.py', 'Agent/runtime_policy.py'),
        'flux': ('Agent/comfy_bridge.py', 'Agent/media_policy.py'),
        'native_image': ('Agent/sdcpp_bridge.py', 'Agent/media_policy.py'),
        'vace': ('Agent/vace_reference.py', 'Agent/comfy_safetensors.py', 'Agent/comfy_bridge.py'),
        'native_video': ('Agent/native_video.py', 'Agent/sdcpp_bridge.py'),
        'ace': ('Agent/music_amd_bridge.py', 'Agent/acestep_amd_entry.py'),
        'music_understanding': ('Agent/music_understanding_bridge.py', 'Agent/music_understanding_runtime.py'),
        'tts': ('Agent/voice_bridge.py', 'Agent/tts_policy.py'),
        'cpu_speech': ('Agent/tts_policy.py', 'Voice/Piper/models/en_US-ljspeech-medium.onnx'),
        'musetalk': ('Agent/musetalk_bridge.py', 'Agent/musetalk_runtime.py', 'Agent/dialogue_portable.py', 'Agent/dialogue_timing.py'),
        'mmaudio': ('Agent/sfx_bridge.py', 'Agent/sfx_amd_bridge.py'),
        'stt': ('Agent/stt_bridge.py', 'SpeechToText/models/whisper-base/model.bin'),
        'media_editing': ('Agent/media_edit_bridge.py', 'Agent/audio_inpaint_amd_bridge.py', 'Agent/dialogue_portable.py', 'Agent/dialogue_timing.py'),
        'preview': ('Agent/media_server.py', 'ControlCenter/native_media_player.py'),
        'web': ('Agent/web_tools.py', 'Agent/web_state.py', 'Agent/web_tls.py'),
        'science': ('Scientific/science_core.py', 'Agent/scientific_tool_bridge.py'),
        'biology': ('Scientific/biology.py','Scientific/biology_tool.py','Agent/science_tools.py'),
        'protein_design': ('Scientific/protein_design.py','Scientific/protein_design_worker.py',
                           'Maintenance/Imports/protein-mpnn.json','Runtime/ProteinDesign/vendor/vanilla_model_weights/v_48_020.pt'),
        'coupled_physics': ('Scientific/coupled_physics.py','Scientific/coupled_physics_tool.py','Scientific/physics_viewer.py'),
        'kicad': ('Scientific/science_core.py','Agent/kicad_windows.py','Tools/KiCad/bin/kicad-cli.exe',
                  'Tools/KiCad/share/kicad/symbols/Device.kicad_sym','Maintenance/Imports/windows-kicad.json') if __import__('os').name == 'nt' else
                 ('Scientific/science_core.py','Runtime/KiCad/linux-x64/bin/kicad-cli'),
        'radeon': ('Agent/amd_runtime.py','Agent/music_amd_bridge.py','Agent/sfx_amd_bridge.py',
                   'Agent/audio_inpaint_amd_bridge.py','Agent/dialogue_portable.py','Agent/radeon_edit.py'),
        'activity': ('ControlCenter/activity_monitor.py','ControlCenter/runtime_activity.py',
                     'ControlCenter/windows_gpu_counters.py','ControlCenter/themed_popup_menu.py','Tools/activity_probe.py'),
        'accounts': ('Agent/local_accounts.py', 'Agent/profile_workspace.py', 'Agent/profile_lazy_state.py',
                     'Agent/profile_hydration.py', 'Agent/profile_shutdown.py', 'ControlCenter/account_gate.py'),
        'missions': ('Agent/mission_runner.py', 'Agent/mission_supervisor.py', 'Agent/mission_schedule.py',
                     'Agent/mission_memory.py', 'Agent/mission_catalog.py', 'Agent/mission_modes.py'),
        'chat_ui': ('ControlCenter/native_chat.py', 'Agent/chat_budgets.py', 'ControlCenter/chat_progress.py',
                    'ControlCenter/chat_zoom.py', 'ControlCenter/conversation_cards.py',
                    'ControlCenter/chat_working_memory.py', 'ControlCenter/chat_evidence.py',
                    'ControlCenter/chat_discovery.py', 'Agent/tool_contracts.py',
                    'ControlCenter/chat_task_checkpoint.py', 'ControlCenter/chat_summary_recovery.py',
                    'ControlCenter/PortableAI_GUI.py', 'ControlCenter/diagnostic_selector.py',
                    'ControlCenter/ui_style_cache.py', 'ControlCenter/rounded_controls.py',
                    'ControlCenter/settings_style.py',
                    'ControlCenter/elegant_native_ui.py', 'ControlCenter/packages_page.py'),
    }
    selected = paths if key == 'all' else {key: paths[key]}
    rows = []
    for name, files in selected.items():
        missing = [path for path in files if not (Path(root)/path).is_file()]
        rows.append({'status': 'FAIL' if missing else 'PASS',
                     'label': resolve(name)['label'] + ' source/assets',
                     'detail': ('Missing: ' + ', '.join(missing)) if missing else
                               'Presence only; no imports, inference or behavioral validation. ' + ', '.join(files)})
    if key=='all':rows.extend(feature_rows(root))
    return rows
