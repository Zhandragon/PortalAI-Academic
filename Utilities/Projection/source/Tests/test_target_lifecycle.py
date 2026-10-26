"""Reuse the established lifecycle contract against the standalone target adapter."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/packages'),str(default_target()/'Maintenance/Tests')]
import test_home_assistant_remote as contracts
import portalai_target


def main():
    cases=('test_lifecycle_confirmation_and_deduplication','test_one_viewer_and_stale_window',
           'test_unsealed_restart_refuses_reopen','test_force_kills_only_owned_and_keeps_recovery',
           'test_sealed_restart_waits_before_launch','test_restart_timeout_does_not_force_or_reopen')
    suite=unittest.TestSuite(contracts.RemoteTests(name) for name in cases)
    with patch.object(contracts,'bridge',portalai_target):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__=='__main__':main()
