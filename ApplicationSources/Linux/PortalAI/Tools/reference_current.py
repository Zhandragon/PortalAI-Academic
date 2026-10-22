"""Validate active bundle references; distinguish optional and retained legacy code."""
import argparse
import ast
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent')]
from maintenance_reports import save
from runtime_policy import load_policy,portable_path

CRITICAL=('PortalAI.exe','ControlCenter/control_center_bootstrap.py','ControlCenter/PortableAI_GUI.py',
          'ControlCenter/settings_page.py','ControlCenter/native_chat.py','ControlCenter/model_connection.py',
          'ControlCenter/chat_progress.py',
          'Agent/runtime_policy.py','Agent/hardware_profiles.json','Agent/service_manager.py','Agent/ai_tools.py',
          'Agent/mission_runner.py','Agent/mission_supervisor.py','Agent/mission_modes.py','Agent/vm_runner.py',
          'Agent/mission_catalog.py','ControlCenter/mission_settings.py',
          'Agent/science_tools.py','Runtime/SciencePackages','Scientific/science_core.py',
          'Agent/scientific_tool_bridge.py','Runtime/ScientificPython/packages',
          'Launchers/Start_PortableAI_Native_v15_133.py','Launchers/Stop_PortableAI.py',
          'Tools/maintenance_reports.py','Tools/storage_current.py','Tools/dependency_check.py',
          'PortalAI.sh','Agent/effort_policy.py','Agent/chat_model_switch.py',
          'ControlCenter/chat_effort_ui.py','ControlCenter/account_gate.py','ControlCenter/account_ui.py',
          'ControlCenter/account_permissions.py','ControlCenter/account_tool_policy.py',
          'ControlCenter/account_reset_ui.py','ControlCenter/admin_profile_ui.py',
          'ControlCenter/profile_context.py','ControlCenter/profile_diagnostics.py','ControlCenter/profile_exports.py',
          'Agent/local_accounts.py','Agent/profile_paths.py','Agent/profile_workspace.py',
          'Agent/profile_runtime.py','Agent/profile_migration.py','Agent/profile_shutdown.py',
          'Agent/profile_reset.py','Agent/admin_profile_access.py','Agent/mission_schedule.py',
          'Agent/mission_memory.py','Agent/mission_context.py','Agent/linux_ml.py','Agent/linux_job.py',
          'Agent/vace_reference.py','Agent/music_understanding_runtime.py','Agent/kicad_linux.py',
          'MusicUnderstanding/runtime_driver.py','ControlCenter/account_presentation.py',
          'Agent/comfy_safetensors.py','ControlCenter/shutdown_ui.py',
          'Agent/assistant_guidance.py','ControlCenter/image_lookup_policy.py',
          'ControlCenter/tool_protocol.py','Agent/dialogue_portable.py',
          'Agent/audio_inpaint_amd_bridge.py','Agent/audio_inpaint_amd_entry.py',
          'Agent/audio_inpaint_math.py','Agent/chat_budgets.py',
          'Agent/profile_lazy_state.py','Agent/profile_hydration.py',
          'ControlCenter/modal_guard.py','ControlCenter/modal_backdrop.py',
          'ControlCenter/chat_zoom.py','ControlCenter/conversation_cards.py',
          'ControlCenter/trace_resize.py','ControlCenter/native_media_player.py',
          'Agent/media_server.py','Tools/diagnostic_catalog.py',
          'Scientific/coupled_physics.py','Scientific/coupled_physics_tool.py','Scientific/physics_viewer.py',
          'ControlCenter/help_catalog.py','Tools/installed_feature_checks.py',
          'Agent/chat_vision_policy.py','Agent/small_vision_assets.json','Tools/vision_diagnostics.py',
          'ControlCenter/native_chat_command.py','ControlCenter/native_thumbnail.py',
          'Agent/windows_demucs.py','Agent/music_cpu.py','Tools/portable_pip_runner.py')


def audit(root):
    root=Path(root).resolve();rows=[]
    def add(s,l,d):rows.append({'status':s,'label':l,'detail':d})
    def source(relative):
        try:return (root/relative).read_text(encoding='utf-8-sig')
        except (OSError,UnicodeError) as exc:
            add('FAIL','Readable source '+relative,str(exc));return ''
    for rel in CRITICAL:add('PASS' if (root/rel).exists() else 'FAIL',rel,'Active dependency')
    try:
        cfg=load_policy(root)
        for m in cfg['models']:
            p=portable_path(root,m['path']);present=p.is_file()
            if m.get('projector'):present=present and portable_path(root,m['projector']).is_file()
            required=cfg.get('selection')==m['id']
            add('PASS' if present else 'FAIL' if required else 'WARN','Model '+m['id'],m['path']+('' if present else ' (not installed; optional unless selected)'))
    except Exception as exc:add('FAIL','Hardware policy',str(exc))
    native=source('ControlCenter/native_chat.py')
    add('PASS' if 'science_tools.py' in native else 'FAIL','Native science route','Agent/science_tools.py + Runtime/SciencePackages remain active; do not remove.')
    add('PASS' if (root/'Agent/scientific_tool_bridge.py').exists() else 'FAIL','CLI science route','Scientific/science_core.py + Runtime/ScientificPython remain active alongside native science.')
    launch=source('ControlCenter/PortableAI_GUI.py')
    for entry in ('maintenance_storage.py','dependency_probe_current.py','reference_integrity.py','system_test.py','component_diagnostics.py','fresh_machine_validator.py','media_stack_verify.py'):
        add('PASS' if entry in launch and (root/'Tools'/entry).is_file() else 'FAIL','GUI action '+entry,'GUI reference and tool entry both present')
    for p in (root/'Launchers').glob('*.py'):
        try:ast.parse(p.read_text(encoding='utf-8-sig'))
        except Exception as exc:add('FAIL','Launcher syntax '+p.name,str(exc))
    for name in ('OpenWebUI','UpdatePayload','Patch','PatchPayload','Payload'):
        if (root/name).exists():add('WARN','Retained '+name,'Historical/runtime/user content retained. Presence is not proof of an active dependency or permission to delete.')
    for name in ('PortalAI.lnk','PortableAI.lnk'):
        if (root/name).exists():add('WARN','Old shortcut '+name,'Use PortalAI.exe; this shortcut may point outside the SSD.')
    from installed_feature_checks import rows as feature_rows
    rows.extend(feature_rows(root))
    counts={s:sum(x['status']==s for x in rows) for s in ('PASS','WARN','FAIL')}
    return {'rows':rows,'counts':counts,'coverage':'Active entry points, policy paths and known dual science routes. Dynamic shell imports and all third-party internals are not proven by this scan.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True);ns=ap.parse_args();root=Path(ns.root).resolve()
    data=audit(root);text=data['coverage']+'\n\n'+'\n'.join(f"[{x['status']}] {x['label']}: {x['detail']}" for x in data['rows'])+f"\n\n{data['counts']}\n"
    code=1 if data['counts']['FAIL'] else 0;save(root,'root_reference_audit',text,data,code);print(text);return code


if __name__=='__main__':raise SystemExit(main())
