"""Deterministic final-case adapters and overlap screening, with no inference.

Prepared cases are not a frozen execution plan. The separate executor must pin
these cases, all inference/grader sources, model identities and runtime settings.
"""
import hashlib
import math

MATH_SUFFIX = '\nPlease reason step by step, and put your final answer within \\boxed{}.'
MMLU_SELECTION_SEED = 'portalai-final-mmlu-pro-v1'
DATASET_ORDER = ('MATH-500', 'GSM8K', 'AMC23', 'Minerva', 'OlympiadBench', 'MMLU-Pro', 'IFEval', 'MBPP')


def normalized(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Expected a nonempty source question')
    return ' '.join(text.casefold().split())


def stable_seed(case_id, sample):
    if not isinstance(case_id, str) or not case_id or type(sample) is not int or sample < 0:
        raise ValueError('Invalid request seed identity')
    return int.from_bytes(hashlib.sha256(('portalai-takehi-v1\0' + case_id + '\0' + str(sample)).encode()).digest()[:4], 'little')


def select_mmlu(rows, count=1000):
    if type(count) is not int or not 1 <= count <= len(rows):
        raise ValueError('Insufficient MMLU-Pro source rows')
    identifiers = [row['question_id'] for row in rows]
    if len(set(identifiers)) != len(rows):
        raise ValueError('MMLU-Pro question IDs are not unique')
    # Hash ordering avoids dependency on a particular Python PRNG implementation.
    return sorted(rows, key=lambda row: (
        hashlib.sha256((MMLU_SELECTION_SEED + '\0' + str(row['question_id'])).encode()).digest(),
        str(row['question_id'])))[:count]


def adapt_row(dataset, row, index):
    if type(index) is not int or index < 0:
        raise ValueError('Invalid source row index')
    if dataset == 'MATH-500':
        identity, question, answer = row['unique_id'], row['problem'], row['answer']
    elif dataset == 'GSM8K':
        identity, question = index, row['question']
        if not isinstance(row['answer'], str) or row['answer'].count('####') != 1:
            raise ValueError('GSM8K answer must have one final-answer delimiter')
        answer = row['answer'].split('####')[1].strip()
    elif dataset in ('AMC23', 'Minerva', 'OlympiadBench'):
        identity, question = row.get('id', index), row['question']
        if dataset == 'OlympiadBench':
            answers = row['final_answer']
            if not isinstance(answers, list) or len(answers) != 1 or not isinstance(answers[0], str):
                raise ValueError('Expected the pinned Olympiad single-string answer format')
            answer = answers[0]
        else:
            answer = row['answer']
            if type(answer) in (int, float):
                if not math.isfinite(answer):
                    raise ValueError('Nonfinite mathematical answer')
                answer = str(answer)
    elif dataset == 'MMLU-Pro':
        options, answer = row['options'], row['answer']
        if not isinstance(options, list) or not 2 <= len(options) <= 10 or not all(isinstance(v, str) for v in options):
            raise ValueError('Invalid MMLU-Pro choice set')
        answer_index = row['answer_index']
        if type(answer_index) is not int or not 0 <= answer_index < len(options) or answer != chr(65 + answer_index):
            raise ValueError('MMLU-Pro answer index and label disagree')
        prompt = (row['question'].strip() + '\n\n' + '\n'.join(chr(65 + i) + '. ' + text for i, text in enumerate(options))
                  + '\nReason through the question and put the single final answer letter in \\boxed{}.')
        return {'id': 'final-MMLU-Pro:' + str(row['question_id']), 'kind': 'choice', 'domain': 'reasoning',
                'dataset': dataset, 'source_question': row['question'], 'prompt': prompt, 'answer': answer,
                'category': row.get('category', '')}
    elif dataset == 'IFEval':
        instructions, kwargs = row['instruction_id_list'], row['kwargs']
        if not isinstance(instructions, list) or not instructions or not isinstance(kwargs, list) or len(instructions) != len(kwargs):
            raise ValueError('IFEval instructions and arguments are not aligned')
        return {'id': 'final-IFEval:' + str(row['key']), 'kind': 'ifeval', 'domain': 'instruction',
                'dataset': dataset, 'source_question': row['prompt'], 'prompt': row['prompt'],
                'key': row['key'], 'instruction_id_list': instructions, 'kwargs': kwargs}
    else:
        raise ValueError('Unsupported final dataset: ' + str(dataset))
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Expected a nonempty mathematical answer string')
    normalized(question)
    return {'id': 'final-' + dataset + ':' + str(identity), 'kind': 'math', 'domain': 'math',
            'dataset': dataset, 'source_question': question, 'prompt': question + MATH_SUFFIX, 'answer': answer}


def screen_cases(cases, prior_questions):
    """Exact normalized overlap only; never imply semantic decontamination."""
    prior = {}
    for identity, text in prior_questions:
        prior.setdefault(normalized(text), identity)
    accepted, excluded, seen_ids, seen_questions = [], [], set(), {}
    for case in cases:
        if case['id'] in seen_ids:
            raise ValueError('Duplicate final case ID: ' + case['id'])
        seen_ids.add(case['id'])
        if not isinstance(case['prompt'], str) or not case['prompt'].strip() or len(case['prompt']) > 65536:
            raise ValueError('Final prompt is empty or exceeds the supported bound')
        fingerprint = normalized(case['source_question'])
        match = prior.get(fingerprint)
        reason = 'exact normalized overlap with practice/discovery pool'
        if match is None:
            match = seen_questions.get(fingerprint)
            reason = 'exact normalized duplicate within final datasets'
        if match is not None:
            excluded.append({'id': case['id'], 'dataset': case['dataset'], 'matched_id': match, 'reason': reason})
            continue
        seen_questions[fingerprint] = case['id']
        accepted.append(case)
    return accepted, excluded


def sample_requests(cases, repetitions):
    result, identifiers = [], set()
    for case in cases:
        count = repetitions[case['dataset']]
        if type(count) is not int or not 1 <= count <= 32:
            raise ValueError('Invalid fixed samples per case')
        for sample in range(count):
            identity = case['id'] + '/sample-' + str(sample)
            if identity in identifiers:
                raise ValueError('Duplicate planned request')
            identifiers.add(identity)
            result.append({'id': identity, 'case_id': case['id'], 'sample': sample,
                           'seed': stable_seed(case['id'], sample)})
    return result
