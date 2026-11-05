"""Derive campaign status from completed evidence, never from desired outcomes.

The terminal confirmation decision requires an independently recomputed audit.
This module does not edit, select, load, or promote a model.
"""
import math


def equivalent(left, right):
    """Allow only accumulation-order rounding in recomputed float summaries."""
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(equivalent(left[key], right[key]) for key in left)
    if type(left) is float and type(right) is float:
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    return type(left) is type(right) and left == right


def model_verdict(row):
    discovery = row.get('discovery')
    if not discovery:
        closed = row.get('status') in (
            'discovery complete without supported contrast',
            'discovery complete without eligible dose')
        return {'complete': closed, 'stage': 'no_admitted_edit' if closed else 'discovery_pending',
                'decision': 'No supported edit was admitted; original retained' if closed else 'Discovery pending',
                'promotion_allowed': False}
    if discovery.get('production_model_changed') is not False:
        raise ValueError('Unexpected production-model mutation in discovery')
    eligible = discovery.get('eligible_for_independent_confirmation')
    if type(eligible) is not bool:
        raise ValueError('Discovery eligibility must be explicit')
    if not eligible:
        return {'complete': True, 'stage': 'discovery_rejected',
                'decision': 'Discovery did not qualify; original retained', 'promotion_allowed': False}
    confirmation = row.get('independent_confirmation')
    audit = row.get('confirmation_audit')
    if not confirmation or not audit:
        return {'complete': False, 'stage': 'confirmation_pending',
                'decision': 'Independent confirmation or its audit remains pending', 'promotion_allowed': False}
    if audit.get('passed') is not True or audit.get('completed_cases_per_arm') != {'baseline': 1152, 'candidate': 1152}:
        raise ValueError('A complete, verified 1,152-pair audit is required')
    paired = confirmation['paired']
    if paired['n'] != 1152 or confirmation.get('production_model_changed') is not False or confirmation.get('base_unchanged') is not True:
        raise ValueError('Incomplete confirmation or changed original model')
    if not equivalent(audit.get('recomputed_paired'), paired) or audit.get('frozen_candidate_sha256') != confirmation.get('frozen_candidate_sha256'):
        raise ValueError('The confirmation summary does not match its audit')
    expected = discovery['model_receipts']['candidate']['candidate_sha256']
    if confirmation['frozen_candidate_sha256'] != expected:
        raise ValueError('Confirmation evaluated another candidate')
    lower = paired['lower_95']
    if type(lower) not in (float, int) or not math.isfinite(lower):
        raise ValueError('Invalid confirmation confidence bound')
    passed = lower > 0
    if (audit['recomputed_paired']['lower_95'] > 0) is not passed:
        raise ValueError('Rounding changes the confirmation decision; explicit review is required')
    if confirmation.get('eligible_for_separate_final_benchmarks') is not passed:
        raise ValueError('Confirmation eligibility differs from the frozen rule')
    if not passed:
        return {'complete': True, 'stage': 'confirmation_not_established',
                'decision': 'Independent confirmation did not establish a gain; original retained',
                'promotion_allowed': False}
    return {'complete': False, 'stage': 'final_benchmarks_required',
            'decision': 'Confirmation passed; separate broad benchmarks and deployment review remain required',
            'promotion_allowed': False}


def campaign_verdict(models):
    expected = {size + '-' + variant for size in ('1.7', '4', '27') for variant in ('standard', 'abliterated')}
    if set(models) != expected:
        raise ValueError('The verdict must cover all six installed model tracks')
    decisions = {name: model_verdict(row) for name, row in models.items()}
    return {'campaign_complete': all(row['complete'] for row in decisions.values()),
            'model_decisions': decisions, 'production_model_replacements': 0,
            'automatic_promotion': False}
