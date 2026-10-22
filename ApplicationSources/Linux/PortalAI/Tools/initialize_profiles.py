"""Explicit one-time owner migration, after verified source recovery snapshots.

Run with bundled Python. Passwords are read with getpass and never accepted in
arguments or configuration. This tool never resets an existing account registry.
Interrupted data migration can be resumed by the same authenticated administrator.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]


def verify_source_recovery(root, backup, mirror):
    from snapshot_owned import verify
    primary=verify(Path(backup).resolve());second=verify(Path(mirror).resolve())
    if primary!=second:raise RuntimeError('Source recovery mirror does not match')
    saved={row['path']:row['sha256'] for row in primary['files']}
    required=[]
    for directory,patterns in ((name,('*.py',)) for name in
                               ('Agent','ControlCenter','Tools','Launchers','Scientific')):
        for pattern in patterns:required.extend((root/directory).glob(pattern))
    for path in set(required):
        relative=path.relative_to(root).as_posix()
        with path.open('rb') as file:actual=hashlib.file_digest(file,'sha256').hexdigest()
        if saved.get(relative)!=actual:raise RuntimeError('Create a current verified source snapshot before account migration')
    return {'verified':True,'files':len(set(required)),'archive_sha256':primary['archive_sha256']}


def provision(root,owner,password,*,pending_users=(),temporary_password=False,resume=False,recovery_directory,
              expected_inventory_digest=None):
    from local_accounts import LocalAccounts
    from mission_runner import process_lock
    from profile_migration import LegacyMigration,legacy_inventory
    from profile_paths import _contained
    from profile_shutdown import stop_owned,verify_stopped
    from profile_reset import ResetCoordinator
    from account_reset_ui import export_reset_plan
    from runtime_policy import atomic_json
    root=Path(root).resolve();accounts=LocalAccounts(root)
    recovery_directory=Path(recovery_directory).resolve()
    if recovery_directory.is_relative_to(root) or not recovery_directory.is_dir():
        raise ValueError('Choose an existing recovery directory outside this portable installation')
    session=None
    backup=None
    with process_lock(_contained(root,root/'Private/profile-runtime.lock')):
        try:
            if resume:
                session=accounts.login(owner,password)
            else:
                reviewed=accounts.private_inventory()
                if expected_inventory_digest is not None and reviewed['digest'] != expected_inventory_digest:
                    raise RuntimeError('Reviewed private-data inventory changed; initialization was not performed')
                session=accounts.initialize_existing(owner,password,reviewed['digest'],
                    pending_users=pending_users,temporary_password=temporary_password)
            if session.role!='admin':raise PermissionError('The initial data owner must be an administrator')
            marker=root/'Private/active-session.json'
            prior=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
            if prior is not None and (not resume or prior.get('state')!='closed' or prior.get('user_id')!=session.user_id):
                raise RuntimeError('A profile has already been opened; use authenticated workspace recovery')
            receipt=stop_owned(root,session,prior)
            if receipt.get('stopped') is not True:raise RuntimeError('Portable writers did not stop')
            proof_path=root/'Private/migration-external-backup.json'
            def external_before_remove(plan,state):
                nonlocal backup
                from profile_workspace import digest
                # The copied workspace is still plaintext and every original
                # still exists. Export only wrapped keys + verified ciphertext.
                migration.store.verify(state['generation'])
                scopes=(root/'Private/Accounts',migration.store.vault)
                rows=[]
                for scope in scopes:
                    for path in scope.rglob('*'):
                        if not path.is_file() or path.name=='registry.lock':continue
                        _contained(root,path)
                        if path.stat().st_nlink!=1:raise RuntimeError('Linked recovery payload requires review')
                        rows.append({'path':path.relative_to(root).as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)})
                rows.sort(key=lambda row:row['path'])
                export_plan={'version':1,'kind':'initial-encrypted-profile-recovery','files':rows,
                             'bytes':sum(row['bytes'] for row in rows),'generation':state['generation']}
                destination=recovery_directory/('PortalAI-private-initial-'+uuid.uuid4().hex+'.zip')
                backup=export_reset_plan(root,export_plan,destination)
                if backup.get('verified') is not True:raise RuntimeError('External private recovery backup did not verify')
                atomic_json(proof_path,{'version':1,'verified':True,'filename':destination.name,
                            'sha256':digest(destination),'bytes':destination.stat().st_size,
                            'user_id':session.user_id,'generation':state['generation']})
                return backup
            migration=LegacyMigration(root,session,before_remove=external_before_remove)
            if migration.journal.exists():
                state=json.loads(migration.journal.read_text(encoding='utf-8'))
                if state.get('phase')=='copying':
                    result=migration.recover_copy(state['digest'],writers_stopped=True)
                else:result=migration.recover_verified(writers_stopped=True)
            elif migration.complete.exists():
                # Resume may need only the final external recovery export.
                if legacy_inventory(root)['files']:raise RuntimeError('New legacy data appeared; reviewed recovery is required')
                migration.store.verify()
                if migration.store.inventory():raise RuntimeError('Existing owner workspace requires recovery')
                result={'migrated':True,'sealed':True,'verified':True,'resumed_export':True,'user_id':session.user_id}
            else:
                reviewed=legacy_inventory(root)
                result=migration.run(reviewed['digest'],writers_stopped=True)
            atomic_json(marker,{'version':1,'user_id':session.user_id,'epoch':uuid.uuid4().hex,
                                'state':'closed','role':'admin','controller_pid':0})
            def writers():
                proof=verify_stopped(root)
                return {'quiescent':proof.get('stopped') is True}
            if backup is None:
                # A resumed already-complete migration gets a fresh verified
                # external copy before reporting completion to its caller.
                plan=ResetCoordinator(root,accounts).plan(session,writer_check=writers)
                destination=recovery_directory/('PortalAI-private-initial-'+uuid.uuid4().hex+'.zip')
                backup=export_reset_plan(root,plan,destination)
            if backup.get('verified') is not True:raise RuntimeError('External private recovery backup did not verify')
            final={**result,'external_recovery_verified':True,'external_recovery_path':backup['path'],
                   'accounts':accounts.list_users(session),'password_not_saved':True}
            # No private filenames, keys or password enter this status receipt.
            atomic_json(root/'Private/profile-initialization.json',{'version':1,'migration_verified':True,
                        'external_recovery_verified':True,'created_at':time.time()})
            return final
        finally:
            if session is not None:accounts.logout(session)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--pending-user',action='append',default=[])
    parser.add_argument('--temporary-password',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--mirror',type=Path,required=True)
    parser.add_argument('--recovery-directory',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    if root!=ROOT:raise ValueError('Run the initializer from the intended portable installation')
    proof=verify_source_recovery(root,args.backup,args.mirror)
    print(json.dumps({'source_recovery':proof,'operation':'resume' if args.resume else 'initialize and migrate'}),flush=True)
    password=getpass.getpass('Administrator password: ')
    try:
        result=provision(root,args.owner,password,pending_users=args.pending_user,
            temporary_password=args.temporary_password,resume=args.resume,recovery_directory=args.recovery_directory)
        print(json.dumps(result,ensure_ascii=True,indent=2))
    finally:password=None


if __name__=='__main__':main()
