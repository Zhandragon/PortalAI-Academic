"""Conservative MBPP adapter for PortalAI's existing pure-function checker.

This produces a documented subset, not a full MBPP result. Test expressions
are parsed as syntax and literals, never evaluated as Python programs. The
caller must verify every adapted reference with the existing owned checker
before freezing a benchmark plan. No generated model answers guide selection.
"""
import ast
import copy
import math


class UnsupportedCase(ValueError):
    pass


def json_value(value):
    """Reject values whose type/keys would change across the grader JSON pipe."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [json_value(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: json_value(item) for key, item in value.items()}
    raise UnsupportedCase('Test literal cannot round-trip through the JSON checker without changing its type')


def literal(node):
    try:
        return json_value(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, RecursionError) as exc:
        raise UnsupportedCase('Test arguments and expected answers must be supported literals') from exc


class RenameFunction(ast.NodeTransformer):
    def __init__(self, original):
        self.original = original

    def visit_FunctionDef(self, node):
        if node.name == self.original:
            node.name = 'solve'
        return self.generic_visit(node)

    def visit_Name(self, node):
        if node.id == self.original:
            return ast.copy_location(ast.Name(id='solve', ctx=node.ctx), node)
        return node


def adapt(row):
    if row.get('test_imports'):
        raise UnsupportedCase('Test imports are outside the restricted checker')
    if type(row.get('task_id')) is not int or not isinstance(row.get('prompt'), str):
        raise UnsupportedCase('Missing task identity or prompt')
    tests = row.get('test_list')
    if not isinstance(tests, list) or not 1 <= len(tests) <= 32:
        raise UnsupportedCase('Expected one to 32 explicit tests')
    checks = []
    name = None
    for text in tests:
        if not isinstance(text, str) or len(text) > 16000:
            raise UnsupportedCase('Test syntax exceeds supported bounds')
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedCase('Invalid test syntax') from exc
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
            raise UnsupportedCase('Each test must contain exactly one assertion')
        test = tree.body[0].test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            raise UnsupportedCase('Only direct equality assertions are supported')
        call = test.left
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.keywords:
            raise UnsupportedCase('Expected a direct positional function call')
        if name is not None and name != call.func.id:
            raise UnsupportedCase('Tests call different entry functions')
        name = call.func.id
        checks.append([[literal(arg) for arg in call.args], literal(test.comparators[0])])
    code = row.get('code')
    if not isinstance(code, str) or len(code) > 16000:
        raise UnsupportedCase('Reference source exceeds supported bounds')
    try:
        reference = ast.parse(code)
    except (SyntaxError, RecursionError) as exc:
        raise UnsupportedCase('Invalid reference syntax') from exc
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(reference)):
        raise UnsupportedCase('Reference imports are outside the restricted checker')
    entries = [node for node in reference.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(entries) != 1:
        raise UnsupportedCase('Expected exactly one top-level entry function')
    if name != 'solve' and any(
        (isinstance(node, ast.Name) and node.id == 'solve')
        or (isinstance(node, (ast.FunctionDef, ast.arg)) and getattr(node, 'name', getattr(node, 'arg', '')) == 'solve')
        for node in ast.walk(reference)
    ):
        raise UnsupportedCase('Renaming would collide with an existing solve binding')
    entry = entries[0]
    if entry.decorator_list or entry.returns is not None or any(
        arg.annotation is not None for arg in ast.walk(entry.args) if isinstance(arg, ast.arg)
    ):
        raise UnsupportedCase('Decorated or annotated references are outside the portable subset')
    # Keep the reference only for isolated validator input. Never put it in a prompt.
    rewritten = RenameFunction(name).visit(copy.deepcopy(reference))
    ast.fix_missing_locations(rewritten)
    signature = copy.deepcopy(entry)
    signature.name = 'solve'
    signature.body = [ast.Pass()]
    signature = ast.unparse(signature).split('\n', 1)[0]
    prompt = (row['prompt'].strip() + '\n\nImplement the following entry function in Python:\n'
              + signature + '\nReturn only a Python code block. Do not import modules, access files or the network, '
              'or mutate the supplied arguments. Helper functions are allowed.')
    return {
        'case': {'id': 'mbpp-sanitized-' + str(row['task_id']), 'kind': 'coding',
                 'prompt': prompt, 'checks': checks},
        'reference_source': ast.unparse(rewritten),
        'original_entry_function': name,
        'original_test_count': len(tests),
        'subset_policy': 'literal-json-tests-pure-function-v1',
    }
