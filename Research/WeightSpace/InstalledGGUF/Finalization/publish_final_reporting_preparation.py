"""Record observed CPU validation and publish the reviewed finalization sources."""
import ast
import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
REPOS = Path('C:/Users/genes/source/PortalAI-mission-audit-20261029')
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))
from experiment import atomic_json, sha, space


files = ['campaign_verdict.py', 'test_campaign_verdict.py', 'audit_confirmation.py',
         'test_confirmation_audit.py', 'prepare_ifeval_runtime.py', 'final_grade_worker.py',
         'final_evaluation.py', 'test_final_evaluation.py']
tests = {'test_campaign_verdict.py': 10, 'test_confirmation_audit.py': 6, 'test_final_evaluation.py': 4}
for name in files:
    tree = ast.parse((LAB / name).read_text())
    if name in tests:
        assert sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(tree)) == tests[name]
frozen = json.loads((LAB / 'experiments/27-abliterated/005-independent-confirmation/frozen.json').read_text())
assert all(sha(ROOT / path) == digest for path, digest in frozen['source_and_data_pins'].items())
report = {'recorded_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
          'passed': True, 'observed_bundled_python_unittest_results': tests,
          'total_tests': sum(tests.values()), 'failures_after_fix': 0,
          'source_sha256': {name: sha(LAB / name) for name in files},
          'frozen_confirmation_source_and_data_pins_preserved': True,
          'final_evaluator_limit_bytes': 512 * 1024**2, 'final_evaluator_threads': 1,
          'fixed_during_validation': 'NLTK imports initially exceeded the process cap through OpenBLAS thread buffers. Single-thread numerical-library settings fixed all three failing IFEval tests without raising the cap.',
          'validation_scope': 'Synthetic CPU cases, real pinned upstream IFEval, and actual pending-campaign publication. No held-out final model generations or completed confirmation audit has been run yet.',
          'real_confirmation_audited': False, 'real_final_benchmarks_run': False,
          'production_model_changed': False}
target = LAB / 'FINAL-REPORTING-VALIDATION.json'
assert not target.exists()
atomic_json(target, report)
sources = ['wait_and_finalize_confirmation.py', 'finalize_confirmed_campaign.py',
           'publish_final_reporting_preparation.py']
for edition in ('Full', 'Academic'):
    destination = REPOS / edition / 'Research/WeightSpace/InstalledGGUF/Finalization'
    destination.mkdir(exist_ok=False)
    for name in sources:
        ast.parse((BASE / name).read_text())
        shutil.copy2(BASE / name, destination / name)
        assert sha(BASE / name) == sha(destination / name)
    shutil.copy2(target, destination / target.name)
    provenance = LAB / 'final-benchmarks/IFEval/portable-runtime/PROVENANCE.json'
    shutil.copy2(provenance, destination / 'IFEVAL-RUNTIME-PROVENANCE.json')
    (destination / 'README.md').write_text(
        '# Finalization source and validation\n\n'
        'The campaign is still running. These sources do not imply that independent '
        'confirmation or final benchmarks have finished.\n\n'
        'The observer holds the original controller process handle, respects pauses, '
        'and never retries failed inference or changes scientific settings. After complete '
        'confirmation it runs the separate provenance/bookkeeping audit. An audited result '
        'that does not establish improvement can finalize the bounded campaign, recheck '
        'D/E originals and installers, and publish the final evidence. Positive confirmation '
        'stops at the mandatory broad-benchmark gate; it cannot promote an edit.\n\n'
        'These are installation-specific publication scripts, preserved for audit rather '
        'than a recipient launcher. Their original location is '
        '`Maintenance/Validation/Weight-Final-r69`; the public reusable editor is under '
        '`ApplicationSources/Windows/PortalAI/Tools/WeightSpace` and the Utilities UI. '
        'GitHub publication uses the maintainer checkout and existing Git credentials; '
        'neither is required for ordinary portable editor/profile use.\n\n'
        'Twenty synthetic CPU tests passed. Three initial IFEval failures exposed excess '
        'OpenBLAS thread-buffer allocation; limiting the evaluator to one thread fixed '
        'them while retaining a 512 MiB process cap. The actual upstream IFEval code and '
        'portable English tokenizer are pinned. Existing SSD Python packages were reused. '
        'Only a 4.3 MB tokenizer archive was downloaded and 237,757 bytes of English data '
        'extracted; no new LLM or host package was installed. '
        'See FINAL-REPORTING-VALIDATION.json and IFEVAL-RUNTIME-PROVENANCE.json.\n',
        encoding='utf-8', newline='\n')
for drive in ('D', 'E'):
    destination = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69/ReportingSource')
    destination.mkdir(exist_ok=False)
    for name, source in [(name, LAB / name) for name in files] + [(name, BASE / name) for name in sources] + [(target.name, target)]:
        space(destination, source.stat().st_size)
        shutil.copy2(source, destination / name)
        assert sha(source) == sha(destination / name)
print(json.dumps({'reporting_CPU_tests_passed': 20, 'source_snapshots_verified_on_D_and_E': True,
                  'frozen_experiment_unchanged': True}), flush=True)
