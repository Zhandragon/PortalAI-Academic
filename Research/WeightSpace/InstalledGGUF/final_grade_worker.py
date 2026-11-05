"""Bounded worker for pinned upstream IFEval and explicit final answer formats."""
import importlib
import json
import random
import re
import sys
import types
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))
from experiment import sha
from evaluation import final_text


def ifeval(case, content):
    base = LAB / 'final-benchmarks/IFEval'
    manifest = json.loads((base.parent / 'manifest.json').read_text())
    for row in manifest['evaluator']['files']:
        assert sha(base / 'evaluator' / row['path']) == row['sha256']
    runtime = base / 'portable-runtime'
    provenance = json.loads((runtime / 'PROVENANCE.json').read_text())
    assert provenance['passed']
    for relative, row in provenance['english_files'].items():
        assert sha(runtime / relative) == row['sha256']
    packages = ROOT.parent / 'Utilities/Portable Abliterator/runtime/Lib/site-packages'
    sys.path.insert(0, str(packages))
    for name, row in provenance['existing_portable_modules'].items():
        module = importlib.import_module(name)
        assert Path(module.__file__).resolve() == (ROOT.parent / row['relative_file']).resolve()
        assert sha(Path(module.__file__)) == row['sha256']
    import nltk
    import langdetect
    nltk.data.path[:] = [str(runtime / 'nltk_data')]
    langdetect.DetectorFactory.seed = 0
    package = types.ModuleType('instruction_following_eval')
    package.__path__ = [str(base / 'evaluator')]
    sys.modules['instruction_following_eval'] = package
    evaluator = importlib.import_module('instruction_following_eval.evaluation_lib')
    example = evaluator.InputExample(key=case['key'], instruction_id_list=case['instruction_id_list'],
                                     prompt=case['prompt'], kwargs=case['kwargs'])
    random.seed(0)
    strict = evaluator.test_instruction_following_strict(example, {case['prompt']: content})
    random.seed(0)
    loose = evaluator.test_instruction_following_loose(example, {case['prompt']: content})
    return {'correct': bool(strict.follow_all_instructions),
            'strict_instruction_results': strict.follow_instruction_list,
            'loose_prompt_correct': bool(loose.follow_all_instructions),
            'loose_instruction_results': loose.follow_instruction_list,
            'grader': 'pinned upstream IFEval; strict prompt-level primary score',
            'language_detector_seed': 0, 'host_nltk_data_used': False}


def grade(case, text):
    content = final_text(text)
    if case['kind'] == 'ifeval':
        return ifeval(case, content)
    if case['kind'] == 'choice':
        matches = re.findall(r'\\boxed\{\s*([A-J])\s*\}', content)
        answer = matches[-1] if matches else None
        return {'correct': answer == case['answer'], 'answer': answer,
                'grader': 'last boxed A-J choice; missing or malformed answer is incorrect'}
    raise ValueError('Unsupported final worker grader')


if __name__ == '__main__':
    data = sys.stdin.buffer.read(2 * 1024**2 + 1)
    if len(data) > 2 * 1024**2:
        raise ValueError('Bounded grader input exceeded 2 MiB')
    request = json.loads(data)
    print(json.dumps(grade(request['case'], request['text'])), flush=True)
