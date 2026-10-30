"""Recognize failed tool serialization without interpreting it as an action.

The model must emit a fresh structured API tool call.  This module never returns
arguments, executes text, or converts a displayed example into a function call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MAX_ENVELOPE_BYTES = 64 * 1024
_NAME = r"[A-Za-z_][A-Za-z0-9_-]{0,127}"
_FUNCTION_XML = re.compile(r"<tool_call>\s*<function=(" + _NAME + r")>\s*(.*?)\s*</function>\s*</tool_call>", re.S)
_PARAMETER_XML = re.compile(r"<parameter=(" + _NAME + r")>(.*?)</parameter>", re.S)
_PROTOCOL_WORD = r"(?:tool[\s_-]*calls?|function[\s_-]*calls?|JSON|XML|API\s+(?:schema|format)|command\s+syntax)"


def read_only_tool_attempt(name, args, root) -> bool:
    """Whether a prior call permits a later format-only inference correction.

    This is deliberately narrower than authorization: returning False never
    forbids the original action.  Read/folder tools and registered web lookups
    may hydrate files or update their own cache, but do not perform arbitrary
    user-requested effects.  Downloads and all other actions remain uncertain.
    """
    if root is None or not isinstance(args, dict):
        return False
    if name in {"read_file", "list_dir", "chat_history"}:
        return True
    if name == 'available_tools':
        return True
    if name in ('knowledge','mcp','workflow','computer','structured','artifact'):
        action=args.get('action')
        safe={'knowledge':{'list','search','read'},'mcp':{'list','tools'},
              'workflow':{'list','describe','status'},'computer':{'windows','status'},
              'structured':{'generate'},'artifact':{'list','read','history','compare'}}
        return isinstance(action,str) and action in safe[name]
    if name == 'web':
        action = args.get('action')
        return isinstance(action, str) and action in {'help', 'search'}
    if name == 'media_tool':
        return args.get('command') == 'model-variants' or args.get('arguments') == ['--help']
    if name != "shell":
        return False
    command = args.get("command")
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_ENVELOPE_BYTES:
        return False
    # Administrators still use a host shell after portable-prefix routing.
    # Literal argv validation alone cannot prove an unquoted `x;command` safe.
    # Reject even quoted instances rather than emulate both cmd.exe and sh.
    if any(character in command for character in "\x00\r\n;&|<>^%$`!()"):
        return False
    try:
        from account_tool_policy import registered_media_argv
        from portable_runtime import bootstrap_python
        root = Path(root)
        argv = registered_media_argv(command, root, Path(bootstrap_python(root)))
        return (len(argv) >= 4
                and Path(argv[1]).resolve() == (root / "Agent/web_tools.py").resolve()
                and argv[2] in {"search", "research", "fetch", "image-search"})
    except (PermissionError, ValueError, OSError, TypeError, ImportError):
        return False


def _strict_json(text: str):
    def object_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("non-JSON constant")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def _function(value) -> bool:
    if not isinstance(value, dict) or set(value) != {"name", "arguments"}:
        return False
    if not isinstance(value["name"], str) or not re.fullmatch(_NAME, value["name"]):
        return False
    arguments = value["arguments"]
    if isinstance(arguments, str):
        try:
            arguments = _strict_json(arguments)
        except (ValueError, TypeError, RecursionError):
            return False
    return isinstance(arguments, dict)


def _api_call(value) -> bool:
    return (isinstance(value, dict)
            and not (set(value) - {"id", "type", "function"})
            and value.get("type", "function") == "function"
            and _function(value.get("function")))


def requests_protocol_example(request) -> bool:
    """Suppress recovery when the user explicitly asks to see the protocol."""
    if not isinstance(request, str):
        return False
    text = request[:12000]
    if not re.search(_PROTOCOL_WORD, text, re.I):
        return False
    return bool(re.search(
        r"\b(?:show|print|provide|write|return|output|explain|describe|document|quote|demonstrate)\b"
        r"[^.!?\n]{0,120}" + _PROTOCOL_WORD
        + r"|\b(?:what|how)\b[^.!?\n]{0,100}" + _PROTOCOL_WORD
        + r"|\b(?:example|sample|syntax|schema|format)\b[^.!?\n]{0,100}" + _PROTOCOL_WORD
        + r"|\b(?:do\s+not|don't|never)\s+(?:execute|run|call)\b", text, re.I))


def classify_text_tool_call(content, *, tool_names=(), request="") -> str | None:
    """Classify a whole serialized envelope, never its contents or arguments.

    Tagged Qwen XML/JSON and explicit API envelopes identify their purpose.
    Bare name/arguments JSON is accepted only for exposed function names.
    Prose surrounding an envelope, malformed/truncated structures, and ordinary
    source code are intentionally not interpreted.
    """
    if not isinstance(content, str) or not content or len(content) > MAX_ENVELOPE_BYTES:
        return None
    if len(content.encode("utf-8", errors="replace")) > MAX_ENVELOPE_BYTES:
        return None
    if requests_protocol_example(request):
        return None
    text = content.strip()
    fence = re.fullmatch(r"```(?:json|xml|text)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    if any(marker in text.upper() for marker in ("<!DOCTYPE", "<!ENTITY", "<?XML")):
        return None
    xml = _FUNCTION_XML.fullmatch(text)
    if xml:
        rest = xml.group(2).strip()
        parameters = set()
        while rest:
            part = _PARAMETER_XML.match(rest)
            if not part or part.group(1) in parameters or len(parameters) >= 32:
                return None
            # A second embedded envelope/parameter is ambiguous, not a command.
            if re.search(r"</?(?:tool_call|function|parameter)(?:[=>\s])", part.group(2)):
                return None
            parameters.add(part.group(1))
            rest = rest[part.end():].strip()
        return "qwen-xml" if parameters else None
    tagged = re.fullmatch(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.S)
    if tagged:
        text = tagged.group(1)
    try:
        value = _strict_json(text)
    except (ValueError, TypeError, RecursionError):
        return None
    if tagged:
        return "qwen-json" if _function(value) else None
    if _function(value):
        return "function-json" if value["name"] in set(tool_names) else None
    if _api_call(value):
        return "api-call-json"
    if not isinstance(value, dict) or set(value) - {"role", "content", "tool_calls"}:
        return None
    if value.get("role", "assistant") != "assistant" or value.get("content") not in (None, ""):
        return None
    calls = value.get("tool_calls")
    if isinstance(calls, list) and 1 <= len(calls) <= 8 and all(_api_call(call) for call in calls):
        return "api-batch-json"
    return None


def correction_message(tool_names=()) -> dict:
    """A bounded inference-only correction; no serialized command is copied."""
    names = sorted({name for name in tool_names if isinstance(name, str) and re.fullmatch(_NAME, name)})
    return {"role": "system", "content": (
        "Host protocol correction: the previous response printed a serialized tool call as ordinary assistant text. "
        "That text was not executed. For an action authorized by the user's current request, issue an actual structured "
        "API tool_calls response using only the supplied functions: " + ", ".join(names) + ". "
        "Do not print <tool_call>, <function=...>, tool JSON, or a fenced command as a substitute for invoking a tool. "
        "Autoedit is an ai_tools.py command invoked through the supplied shell function, not a separate function name. "
        "Earlier tool results in this conversation remain valid: do not repeat a completed or uncertain action; continue only remaining authorized work. "
        "If the user only requested an explanation or example, answer it without executing anything. "
        "Do not claim that any action completed until its tool result confirms completion."
    )}
