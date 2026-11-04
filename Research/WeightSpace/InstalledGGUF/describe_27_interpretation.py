"""Report wording ambiguities without relabeling or retuning a frozen experiment."""
import hashlib
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from experiment import atomic_json, paired_summary, sha
from extend_discovery import records

AMBIGUITIES = {
    'gsm8k_train_1337': {
        'official_answer': '27',
        'interpretation': 'The question says shoes, while its solution counts pairs. The original correctly derives 27 pairs and answers 54 individual shoes. Its official score is false; this is not a clear arithmetic failure.'},
    'gsm8k_train_4302': {
        'official_answer': '4800',
        'interpretation': 'The original correctly gives 3000 pizzas and 1800 hot dogs. The official answer expects their combined total, 4800. The scalar-box grader rejects the component answer despite correct arithmetic.'},
}


def main():
    with (LAB / 'practice.jsonl').open(encoding='utf-8') as stream:
        practice = {row['id']: row for row in map(json.loads, stream) if row['id'] in AMBIGUITIES}
    for key, detail in AMBIGUITIES.items():
        assert practice[key]['answer'] == detail['official_answer']
    for model in ('27-standard', '27-abliterated'):
        folder = LAB / 'experiments' / model
        destination = folder / 'INTERPRETATION-SENSITIVITY.json'
        assert not destination.exists(), 'Existing sensitivity results require review.'
        prior_notes = folder / 'INTERPRETATION-NOTES.json'
        assert prior_notes.is_file(), 'The earlier interpretation record must remain preserved.'
        natural = {row['id']: row for row in records(folder)}
        relevant = {key: detail for key, detail in AMBIGUITIES.items()
                    if key in natural and not natural[key]['grading']['correct']}
        assert 'gsm8k_train_1337' in relevant
        if model == '27-abliterated':
            assert set(relevant) == set(AMBIGUITIES)
        note = {
            'model': model, 'official_grades_changed': False, 'recipe_or_selection_changed': False,
            'interpretations': relevant,
            'practice_file_sha256': sha(LAB / 'practice.jsonl'),
            'prior_interpretation_notes_sha256': sha(prior_notes),
            'caveat': 'Post-hoc descriptive sensitivity, not a revised selection rule or independent confirmation. Do not call official-score changes on these cases established reasoning improvements.'}
        screen = folder / '004-generation-screen'
        if (screen / 'summary.json').is_file():
            cases = json.loads((screen / 'cases.json').read_text())
            excluded = set(relevant) & {case['id'] for case in cases}
            arms = {}
            hashes = {}
            for arm in ('baseline', 'candidate', 'random'):
                arms[arm] = {}
                hashes[arm] = {}
                for case in cases:
                    name = hashlib.sha256(case['id'].encode()).hexdigest()[:20] + '.json'
                    path = screen / arm / name
                    value = json.loads(path.read_text())
                    assert value['id'] == case['id'] and type(value['grading']['correct']) is bool
                    if case['id'] in excluded:
                        hashes[arm][case['id']] = sha(path)
                    else:
                        arms[arm][case['id']] = value['grading']['correct']
            domains = {}
            for domain in sorted({case['domain'] for case in cases}):
                keys = [case['id'] for case in cases if case['domain'] == domain and case['id'] not in excluded]
                domains[domain] = paired_summary({key: arms['baseline'][key] for key in keys},
                                                {key: arms['candidate'][key] for key in keys})
            paired = paired_summary(arms['baseline'], arms['candidate'])
            note['sensitivity_excluding_ambiguous_cases'] = {
                'excluded_ids': sorted(excluded), 'record_sha256': hashes,
                'scores': {arm: {'correct': sum(values.values()), 'total': len(values)} for arm, values in arms.items()},
                'paired': paired, 'domains': domains,
                'would_meet_discovery_comparison_rule': paired['gain'] > 0
                    and sum(arms['candidate'].values()) > sum(arms['random'].values())
                    and all(row['gain'] >= 0 for row in domains.values())}
        else:
            assert model == '27-standard'
            kept = {key: value for key, value in natural.items() if key not in relevant}
            note['natural_discovery_excluding_ambiguous_cases'] = {
                'correct': sum(row['grading']['correct'] for row in kept.values()),
                'total': len(kept), 'incorrect': sum(not row['grading']['correct'] for row in kept.values()),
                'no_edit_was_admitted': True}
        atomic_json(destination, note)
        print(json.dumps({'model': model, 'documented_ambiguities': sorted(relevant), 'official_grades_changed': False}), flush=True)


if __name__ == '__main__':
    main()
