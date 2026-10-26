"""Import ordinary user setup data through the authenticated Accounts UI."""
from pathlib import Path
import json


def show_setup(gate, request_path=None, *, apply_requested=False, receipt_path=None):
    from account_ui import _Dialog
    from account_setup import load_request,apply,check_connections
    if gate.locked or not gate.session.active:return
    dialog=_Dialog(gate.app,'Import connections and mission',gate.colors,jobs=gate.controller.jobs)
    dialog.label('Import encrypted credentials into this account, and create a normal saved mission and paused schedule. Existing missions and schedules are preserved.')
    path=dialog.entry('Setup request JSON file')
    if request_path:path.set(str(request_path))
    dialog.label('Credentials stay encrypted on this drive and unlock with your PortalAI sign-in. The mission sees named operations, not passwords or tokens. Full host access is not an OS sandbox.')
    def run():
        try:spec=load_request(path.get())
        except Exception:
            dialog.status.set('Could not read a valid setup request. Choose the prepared JSON file.');return
        def work():
            result=apply(gate.root,gate.session,spec)
            result['checks']=check_connections(gate.root,gate.session,result['connections'])
            # Sanitized receipt is private profile data, never a public installer.
            from profile_paths import private_path
            from runtime_policy import atomic_json
            atomic_json(private_path(gate.root,'Data/Accounts/SetupReceipts/'+spec['id']+'.json'),result)
            if receipt_path:
                # Explicit CLI destination; never take an export destination from
                # the imported document, and never replace an existing file.
                destination=Path(receipt_path)
                try:
                    if not destination.is_absolute():raise ValueError()
                    with destination.open('x',encoding='utf-8') as output:
                        json.dump(result,output,indent=2)
                        output.flush()
                        import os
                        os.fsync(output.fileno())
                except (OSError,ValueError):result['receipt_export']='Not exported; destination must be a new writable absolute file.'
            return result
        def done(result):
            lines=['Created mission: '+result['mission_id'],'Created schedule: '+result['schedule_id'],'Schedule is paused. Enable it in Persistence > Schedules when ready.']
            lines += [name+': '+check['status'] for name,check in result['checks'].items()]
            dialog.status.set('\n'.join(lines))
            dialog.label('\n'.join(lines))
            gate.app._portalai_last_account_setup=result
        dialog.run(work,done)
    dialog.button('Import and create records',run,enabled=gate.session.role=='admin')
    dialog.button('Close',dialog.close)
    dialog.status_line()
    if request_path and apply_requested:dialog.win.after(150,run)
    return dialog
