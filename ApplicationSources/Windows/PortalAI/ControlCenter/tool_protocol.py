"""Recognize failed tool serialization without interpreting it as an action.

The model must emit a fresh structured API tool call.  This module never returns
arguments, executes text, or converts a displayed example into a function call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MAX_ENVELOPE_BYTES = 64 * 1024


class ToolArgumentStream:
    """Reject stalled JSON formatting without limiting text inside string values.

    This validates framing only. It never returns arguments or authorizes a call;
    the complete response still needs its terminal marker and batch validation.
    """
    MAX_FORMATTING_WHITESPACE = 256
    MAX_MEMBER_NAME = 256

    def __init__(self):
        self.quoted = False
        self.escaped = False
        self.unicode_digits = 0
        self.started = False
        self.complete = False
        self.depth = 0
        self.whitespace = 0
        self.containers = []
        self.member_name = False
        self.member_chars = 0

    def feed(self, fragment):
        for char in fragment:
            if self.quoted:
                # Field names are protocol, unlike unbounded user text values.
                # A broken escaped quote can otherwise keep one name open for
                # the entire token allowance while still looking like a string.
                if self.member_name:
                    self.member_chars += 1
                    if self.member_chars > self.MAX_MEMBER_NAME:
                        raise ValueError('Tool argument JSON member name exceeded 256 characters')
                if ord(char) < 32:
                    raise ValueError('Unescaped control character in JSON string')
                if self.unicode_digits:
                    if char not in '0123456789abcdefABCDEF':
                        raise ValueError('Invalid Unicode escape in JSON string')
                    self.unicode_digits -= 1
                elif self.escaped:
                    if char not in '"\\/bfnrtu':
                        raise ValueError('Invalid escape in JSON string')
                    if char == 'u':self.unicode_digits = 4
                    self.escaped = False
                elif char == '\\':
                    self.escaped = True
                elif char == '"':
                    self.quoted = False
                continue
            if char in ' \t\r\n':
                self.whitespace += 1
                if self.whitespace > self.MAX_FORMATTING_WHITESPACE:
                    raise ValueError('Tool argument serialization stalled in excessive JSON formatting whitespace')
                continue
            self.whitespace = 0
            if self.complete:
                raise ValueError('Tool argument serialization continued after its complete JSON object')
            if not self.started:
                if char != '{':
                    raise ValueError('Tool arguments must start with a JSON object')
                self.started = True
            if char == '"':
                self.quoted = True
                self.member_name = bool(self.containers and self.containers[-1] == ['{', True])
                self.member_chars = 0
            elif char == ':' and self.containers:
                self.containers[-1][1] = False
            elif char == ',' and self.containers:
                self.containers[-1][1] = self.containers[-1][0] == '{'
            elif char in '{[':
                self.depth += 1
                self.containers.append([char, char == '{'])
            elif char in '}]':
                if not self.containers or self.containers[-1][0] != {'}':'{', ']':'['}[char]:
                    raise ValueError('Mismatched JSON container in tool arguments')
                self.containers.pop()
                self.depth -= 1
                if self.depth == 0:
                    self.complete = True


def verified_inert_download(name, args, result, execution):
    """A completed inbound file permits fresh inference, never replay or execution.

    Arbitrary writes and missing/failed/cancelled download receipts stay unsafe.
    The native worker owns byte verification; web page prose cannot create this
    download result envelope. Action receipts and duplicate checks stay effectful.
    """
    if (name != 'web' or not isinstance(args, dict) or args.get('action') != 'download'
            or not execution.get('dispatched') or execution.get('outcome') != 'returned'):
        return False
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict) or data.get('ok') is not True:
        return False
    row = data.get('result')
    return (isinstance(row, dict) and row.get('download_verified') is True
            and row.get('executed') is False and isinstance(row.get('path'), str)
            and bool(row['path']) and type(row.get('bytes')) is int and row['bytes'] > 0
            and isinstance(row.get('sha256'), str)
            and re.fullmatch('[0-9a-fA-F]{64}', row['sha256']) is not None)
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
    if name=='portal_ui':return args.get('action','state')=='state'
    if name in {"read_file", "file_inspect", "list_dir", "chat_history", "tool_help"}:
        return True
    if name in ('available_tools','media_plan'):
        return True
    if name=='project':return args.get('action') in {'list','scan','search','edits','diff'}
    if name=='verify':
        checks=args.get('checks',[args])
        return args.get('action')=='read' or (args.get('action')=='run' and isinstance(checks,list) and all(isinstance(c,dict) and c.get('kind') in {'file','contains','sha256','json_value'} for c in checks))
    if name=='task':return args.get('action')=='read'
    if name in ('knowledge','mcp','workflow','computer','structured','artifact','skill'):
        action=args.get('action')
        safe={'knowledge':{'list','search','read'},'mcp':{'list','tools'},
              'workflow':{'list','describe','status'},'computer':{'windows','status','state','elements','screenshot'},
              'structured':{'generate'},'artifact':{'list','libraries','read','history','compare'},'skill':{'list','read','assets','file'}}
        return isinstance(action,str) and action in safe[name]
    if name == 'web':
        action = args.get('action')
        # These routes retrieve public documents/metadata or parse cached data.
        # They cannot select an HTTP method, drive a browser or publish a file.
        # Keep arbitrary requests, downloads and browser actions outside this set.
        return isinstance(action, str) and action in {
            'help', 'search', 'image_search', 'read', 'site_search', 'site_query',
            'catalog_search', 'discover', 'data', 'media_info'}
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


def truncation_correction_message(tool_names):
    """A fresh bounded inference request; partial arguments are never reused."""
    names=tuple(str(name) for name in tool_names)
    return {'role':'system','content':
        'Host protocol correction: your last response could not finish serializing a tool call within its format/reply limits. '
        'No tools from that response were executed. Use the original user request and saved outcomes above. '
        'Return one concise, complete structured API tool call for the next unresolved step, or a concise final answer/blocker. '
        'Omit further hidden reasoning and unnecessary narration. Use only these supplied functions: '+', '.join(names)+'. '
        'Do not repeat completed or uncertain actions. Do not append to partial JSON, invent missing results, '
        'or reduce the user-requested output merely to fit the tool envelope. Large text/file contents should use '
        'supported bounded writes and saved paths. This is the only format correction allowed in this request.'}


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
