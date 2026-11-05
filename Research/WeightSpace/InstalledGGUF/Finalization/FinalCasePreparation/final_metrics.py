"""Complete paired final metrics; this module cannot authorize promotion.

Repeated generations are averaged within each question. Datasets have equal
weight within their domain, so a large dataset cannot mask a smaller domain.
Elapsed time covers native generation only; actual-harness latency is separate.
"""
import collections
import math
from final_case_plan import sample_requests

REQUIRED_DOMAINS = ('math', 'coding', 'tools', 'instruction')


def summarize(plan, results):
    cases = {case['id']: case for case in plan['cases']}
    if len(cases) != len(plan['cases']) or not cases:
        raise ValueError('Expected nonempty unique final cases')
    expected_requests = sample_requests(plan['cases'], plan['samples_per_case'])
    if plan['requests'] != expected_requests:
        raise ValueError('Final request IDs, seeds, repetitions or order differ from the plan')
    requests = {row['id']: row for row in expected_requests}
    if set(results) != {'baseline', 'candidate'} or any(set(values) != set(requests) for values in results.values()):
        raise ValueError('Incomplete, extra or unpaired final results')
    by_case = {arm: collections.defaultdict(list) for arm in results}
    telemetry = {arm: {'tokens': 0, 'native_generation_seconds': 0.0, 'cutoffs': 0, 'requests': 0} for arm in results}
    for arm in results:
        for identity, request in requests.items():
            value = results[arm][identity]
            if value.get('id') != identity or type(value.get('grading', {}).get('correct')) is not bool:
                raise ValueError('Invalid final response identity or grade')
            if value['grading'].get('infrastructure_error'):
                raise ValueError('A grader infrastructure error cannot be counted as a model failure')
            if value.get('finish') not in ('stop', 'length'):
                raise ValueError('Missing or invalid response finish reason')
            seconds, tokens = value.get('seconds'), value.get('tokens')
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError('Invalid generation time')
            if type(tokens) is not int or not 1 <= tokens <= 32768:
                raise ValueError('Invalid generation token count')
            by_case[arm][request['case_id']].append(int(value['grading']['correct']))
            stats = telemetry[arm]
            stats['tokens'] += tokens
            stats['native_generation_seconds'] += seconds
            stats['cutoffs'] += value['finish'] == 'length'
            stats['requests'] += 1
    means = {arm: {key: sum(values) / len(values) for key, values in by_case[arm].items()} for arm in results}
    datasets = {}
    for case in cases.values():
        dataset, domain = case['dataset'], case['domain']
        if dataset not in datasets:
            datasets[dataset] = {'domain': domain, 'case_ids': []}
        if datasets[dataset]['domain'] != domain:
            raise ValueError('A dataset maps to inconsistent domains')
        datasets[dataset]['case_ids'].append(case['id'])
    for dataset, row in datasets.items():
        identities = row.pop('case_ids')
        n = len(identities)
        baseline = math.fsum(means['baseline'][key] for key in identities) / n
        candidate = math.fsum(means['candidate'][key] for key in identities) / n
        row.update(unique_questions=n, samples_per_question=plan['samples_per_case'][dataset],
                   requests_per_arm=n * plan['samples_per_case'][dataset],
                   baseline_accuracy=baseline, candidate_accuracy=candidate, gain=candidate - baseline,
                   questions_with_higher_mean=sum(means['candidate'][key] > means['baseline'][key] for key in identities),
                   questions_with_lower_mean=sum(means['candidate'][key] < means['baseline'][key] for key in identities))
    domains = {}
    for domain in sorted({row['domain'] for row in datasets.values()}):
        rows = {name: value for name, value in datasets.items() if value['domain'] == domain}
        baseline = math.fsum(row['baseline_accuracy'] for row in rows.values()) / len(rows)
        candidate = math.fsum(row['candidate_accuracy'] for row in rows.values()) / len(rows)
        domains[domain] = {'datasets': sorted(rows), 'baseline_accuracy': baseline,
                           'candidate_accuracy': candidate, 'gain': candidate - baseline,
                           'unique_questions': sum(row['unique_questions'] for row in rows.values())}
    missing = sorted(set(REQUIRED_DOMAINS) - set(domains))
    return {
        'all_planned_requests_complete': True,
        'unique_questions': len(cases), 'requests_per_arm': len(requests),
        'datasets': datasets, 'domains': domains, 'telemetry': telemetry,
        'native_generation_latency_ratio': telemetry['candidate']['native_generation_seconds'] / telemetry['baseline']['native_generation_seconds'],
        'weighting': 'Mean repetitions per question; equal question weight per dataset; equal dataset weight per domain.',
        'required_domains': list(REQUIRED_DOMAINS), 'missing_required_domains': missing,
        'domain_regressions_over_two_percentage_points': [name for name, row in domains.items() if row['gain'] < -0.02 - 1e-12],
        'required_domain_mean_gain': None if missing else math.fsum(domains[name]['gain'] for name in REQUIRED_DOMAINS) / len(REQUIRED_DOMAINS),
        'actual_harness_latency_verified': False,
        'promotion_permitted': False,
        'limitations': 'Metrics alone do not verify provenance, independent confirmation, actual-harness behavior, D/E installation checks or promotion gates.',
    }
