"""CPU-only, post-hoc completion diagnostics; never select or promote an edit."""
import hashlib
import json
import re
import statistics
from pathlib import Path

LAB = Path(__file__).resolve().parent


def tail_repetition(text):
    """Same descriptive four-word tail statistic used during natural discovery."""
    words = text.lower().split()[-200:]
    counts = {}
    for index in range(max(0, len(words) - 3)):
        key = tuple(words[index:index + 4])
        counts[key] = counts.get(key, 0) + 1
    return sum(count for count in counts.values() if count >= 3) / max(1, len(words) - 3)


def analyze(folder):
    screen = folder / '004-generation-screen'
    if not (screen / 'summary.json').is_file():
        return {'status': 'Comparison incomplete; not analyzed'}
    summary = json.loads((screen / 'summary.json').read_text(encoding='utf-8'))
    cases = json.loads((screen / 'cases.json').read_text(encoding='utf-8'))
    case_ids = {case['id'] for case in cases}
    assert len(case_ids) == len(cases), 'Duplicate case IDs'
    arms = {}
    for arm in ('baseline', 'candidate', 'random'):
        records = {}
        for path in sorted((screen / arm).glob('*.json')):
            if not re.fullmatch(r'[a-f0-9]{20}\.json', path.name):
                continue
            raw = path.read_bytes()
            row = json.loads(raw)
            key = row['id']
            assert key not in records and key in case_ids
            assert path.stem == hashlib.sha256(key.encode()).hexdigest()[:20]
            assert row['finish'] in ('stop', 'length')
            assert type(row['grading']['correct']) is bool
            assert isinstance(row['tokens'], int) and row['tokens'] >= 0
            repetition = tail_repetition(row['text'])
            records[key] = {
                'record_sha256': hashlib.sha256(raw).hexdigest(),
                'correct': row['grading']['correct'],
                'finish': row['finish'], 'tokens': row['tokens'],
                'repeated_tail_fraction': repetition,
                'repetitive_tail': repetition >= 0.5,
            }
        assert set(records) == case_ids, 'Missing or extra cases in ' + arm
        values = list(records.values())
        arms[arm] = {
            'cases': len(values),
            'correct': sum(row['correct'] for row in values),
            'correct_with_natural_stop': sum(row['correct'] and row['finish'] == 'stop' for row in values),
            'reply_limit_hits': sum(row['finish'] == 'length' for row in values),
            'repetitive_tails': sum(row['repetitive_tail'] for row in values),
            'total_generated_tokens': sum(row['tokens'] for row in values),
            'median_generated_tokens': statistics.median(row['tokens'] for row in values),
            'cases_with_diagnostics': records,
        }
    assert arms['baseline']['correct'] == summary['paired']['baseline_correct']
    assert arms['candidate']['correct'] == summary['paired']['candidate_correct']
    assert arms['random']['correct'] == summary['random_control']['candidate_correct']
    result = {'status': 'Completed comparison analyzed', 'arms': arms}
    notes_path = folder / 'INTERPRETATION-NOTES.json'
    if notes_path.is_file():
        notes = json.loads(notes_path.read_text(encoding='utf-8'))
        assert notes['scores_modified'] is False
        excluded = sorted({note['id'] for note in notes['notes']
                           if note.get('classification') == 'answer-key unit ambiguity'} & case_ids)
        if excluded:
            result['post_hoc_excluding_ambiguous_items'] = {
                'excluded_ids': excluded,
                'frozen_grades_and_admission_unchanged': True,
                'used_for_recipe_selection': False,
                'arms': {arm: {
                    'cases': len(case_ids) - len(excluded),
                    'correct': sum(row['correct'] for key, row in values['cases_with_diagnostics'].items() if key not in excluded),
                } for arm, values in arms.items()},
            }
    return result


def report():
    protocol = json.loads((LAB / 'protocol.json').read_text(encoding='utf-8'))
    return {
        'purpose': 'Post-hoc diagnostics only; original frozen grading, sampling and admission gates remain unchanged.',
        'limits': [
            'Repeated tail text is a heuristic, not proof of a reasoning loop; non-repetitive text can also waste reasoning.',
            'An extracted correct answer can occur in a reply that reaches its token limit. Both facts are reported.',
            'Token counts are not wall-clock speed. Discovery may overlap CPU release work; these are not final latency measurements.',
            'No output text, private data or model weights are included.',
        ],
        'models': {name: analyze(LAB / 'experiments' / name) for name in protocol['models']},
    }


if __name__ == '__main__':
    print(json.dumps(report(), indent=2))
