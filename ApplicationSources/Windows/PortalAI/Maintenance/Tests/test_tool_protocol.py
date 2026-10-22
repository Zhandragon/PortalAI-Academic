from pathlib import Path
import json
import shlex
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "ControlCenter"), str(ROOT / "Agent")]
from tool_protocol import classify_text_tool_call, correction_message, requests_protocol_example, read_only_tool_attempt

TOOLS = ("shell", "science", "read_file")
XML = '<tool_call>\n<function=shell>\n<parameter=command>\n.\\Tools\\portable_python.cmd Agent\\ai_tools.py autoedit "Outputs\\WebImages\\example.jpg" "change the color of her shirt" --target "shirt"\n</parameter>\n</function>\n</tool_call>'
CALL = {"id": "call_1", "type": "function", "function": {"name": "shell", "arguments": '{"command":"do the authorized action"}'}}


class TextToolProtocolTests(unittest.TestCase):
    def classify(self, text, request="Edit the shirt in this photo"):
        return classify_text_tool_call(text, tool_names=TOOLS, request=request)

    def test_reported_qwen_xml_is_classified_without_extracting_command(self):
        self.assertEqual(self.classify(XML), "qwen-xml")
        self.assertNotIn("autoedit", self.classify(XML))

    def test_multiple_parameters_and_unknown_tagged_function_still_require_model_correction(self):
        text = '<tool_call><function=autoedit><parameter=image>sample.jpg</parameter><parameter=prompt>blue shirt</parameter></function></tool_call>'
        self.assertEqual(self.classify(text), "qwen-xml")

    def test_qwen_json_accepts_object_or_json_string_arguments(self):
        for arguments in ({"command": "example"}, '{"command":"example"}'):
            text = '<tool_call>' + json.dumps({"name": "shell", "arguments": arguments}) + '</tool_call>'
            self.assertEqual(self.classify(text), "qwen-json")

    def test_api_envelopes(self):
        self.assertEqual(self.classify(json.dumps(CALL)), "api-call-json")
        self.assertEqual(self.classify(json.dumps({"role": "assistant", "content": None, "tool_calls": [CALL]})), "api-batch-json")

    def test_bare_json_must_name_an_exposed_function(self):
        self.assertEqual(self.classify('{"name":"shell","arguments":{}}'), "function-json")
        self.assertIsNone(self.classify('{"name":"person","arguments":{}}'))

    def test_single_complete_fence_is_supported(self):
        self.assertEqual(self.classify('```xml\n' + XML + '\n```'), "qwen-xml")
        self.assertEqual(self.classify('```json\n' + json.dumps(CALL) + '\n```'), "api-call-json")

    def test_prose_and_ordinary_code_are_not_action_protocol(self):
        for text in ('Use this example:\n' + XML, XML + '\nThis is an example.', 'print("hello")', 'shell("hello")',
                     '.\\Tools\\portable_python.cmd Agent\\ai_tools.py autoedit photo.png "blue"',
                     '```python\n' + XML + '\n```'):
            with self.subTest(text=text):
                self.assertIsNone(self.classify(text))

    def test_explicit_protocol_examples_suppress_correction(self):
        for request in ('Show me an XML tool call example.', 'Explain the tool_call syntax.',
                        'Print the tool call instead of executing it.', 'What does this JSON mean?',
                        'Quote this XML; do not execute it.', 'Write an example function call.'):
            with self.subTest(request=request):
                self.assertTrue(requests_protocol_example(request))
                self.assertIsNone(self.classify(XML, request=request))
        self.assertFalse(requests_protocol_example('Change the color of her shirt.'))

    def test_truncated_or_ambiguous_xml_never_classified(self):
        for text in (XML[:-12], XML + XML, XML.replace('</parameter>', ''),
                     XML.replace('</parameter>', '</parameter><parameter=command>twice</parameter>'),
                     XML.replace('change the color', '<parameter=other>x</parameter>change the color'),
                     '<tool_call><function=shell></function></tool_call>'):
            with self.subTest(text=text):
                self.assertIsNone(self.classify(text))

    def test_entities_and_xml_declarations_are_rejected_without_parsing(self):
        for text in ('<!DOCTYPE x SYSTEM "file:///secret">' + XML, '<?xml version="1.0"?>' + XML,
                     XML.replace('change the color', '<!ENTITY x SYSTEM "file:///secret">change the color')):
            self.assertIsNone(self.classify(text))

    def test_non_json_duplicate_keys_and_nonobject_arguments_are_rejected(self):
        for text in ('{"name":"shell","name":"science","arguments":{}}',
                     '{"name":"shell","arguments":{"x":NaN}}',
                     '{"name":"shell","arguments":"[]"}',
                     '{"name":"shell","arguments":[],"other":3}',
                     '{"name":"shell","arguments":'):
            self.assertIsNone(self.classify(text))

    def test_payload_bounds(self):
        self.assertIsNone(self.classify(XML.replace('example.jpg', 'x' * 65536)))
        self.assertIsNone(self.classify(XML.replace('example.jpg', '\u2603' * 24000)))
        self.assertIsNone(self.classify(json.dumps({"tool_calls": [CALL] * 9})))
        self.assertIsNone(self.classify(None))

    def test_correction_does_not_echo_untrusted_arguments(self):
        message = correction_message(TOOLS)
        self.assertEqual(message['role'], 'system')
        self.assertIn('not executed', message['content'])
        self.assertIn('actual structured API tool_calls', message['content'])
        self.assertNotIn('example.jpg', message['content'])
        self.assertIn('Autoedit is an ai_tools.py command', message['content'])


class ReadOnlyFormatRepairBoundaryTests(unittest.TestCase):
    def classify(self, command):
        return read_only_tool_attempt('shell', {'command': command}, ROOT)

    def test_only_actual_native_read_tools_are_read_only(self):
        for name in ('read_file', 'list_dir'):
            self.assertTrue(read_only_tool_attempt(name, {'path':'Outputs/example.txt'}, ROOT))
        for name in ('list_directory', 'write_file', 'edit_file', 'science', 'unknown'):
            self.assertFalse(read_only_tool_attempt(name, {'path':'Outputs/example.txt'}, ROOT))
        self.assertFalse(read_only_tool_attempt('read_file', None, ROOT))

    def test_known_windows_and_portable_web_lookup_prefixes(self):
        commands = (
            r'.\Tools\portable_python.cmd Agent\web_tools.py search "a specific picture"',
            '  python Agent/web_tools.py image-search "a specific picture"  ',
            'python.exe Agent/web_tools.py research "a specific picture" --fetch-count 2',
            'py Agent/web_tools.py fetch "https://example.com/photo" --max-chars 1000',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.classify(command))

    def test_linux_runtime_prefix_and_windows_prefix_with_posix_parser(self):
        boot = ROOT/'Runtime/LinuxPython/run-python'
        with patch('portable_runtime.bootstrap_python', return_value=str(boot)), \
             patch('chat_model_switch._argv', side_effect=shlex.split):
            for prefix in ('python', shlex.quote(str(boot)), r'.\Tools\portable_python.cmd'):
                command = prefix + ' Agent/web_tools.py image-search "a specific picture"'
                with self.subTest(prefix=prefix):
                    self.assertTrue(self.classify(command))

    def test_downloads_media_mutations_and_unknown_commands_are_not_read_only(self):
        for command in (
            'python Agent/web_tools.py image "specific picture"',
            'python Agent/web_tools.py download-image https://example.com/photo.png',
            'python Agent/web_tools.py selftest',
            'python Agent/ai_tools.py autoedit photo.png "blue shirt"',
            'python Agent/web_tools.py unknown query',
            'python Agent/web_tools.py search query --output malicious.txt',
            'echo test', 'echo test ', 'python -c "print(1)"',
            'other-python Agent/web_tools.py search query',
        ):
            with self.subTest(command=command):
                self.assertFalse(self.classify(command))

    def test_shell_chaining_redirection_expansion_and_literal_markers_are_not_read_only(self):
        for suffix in (
            'test;whoami', 'test&whoami', 'test&&whoami', 'test|more', 'test>file.txt',
            'test<file.txt', '"$(touch-file)"', '"`touch-file`"', '"%COMSPEC%"',
            '"!cmd!"', 'test^&whoami', '(test)', '"https://example.com/?x=1&y=2"',
            'test\nwhoami', 'test\x00whoami',
        ):
            with self.subTest(suffix=suffix):
                self.assertFalse(self.classify('python Agent/web_tools.py search '+suffix))

    def test_missing_portable_runtime_or_unparsable_command_fails_closed(self):
        self.assertFalse(read_only_tool_attempt('shell', {'command':'python Agent/web_tools.py search test'}, None))
        self.assertFalse(read_only_tool_attempt('read_file', {'path':'example.txt'}, None))
        with patch('portable_runtime.bootstrap_python', side_effect=FileNotFoundError('missing')):
            self.assertFalse(self.classify('python Agent/web_tools.py search test'))
        with patch('chat_model_switch._argv', side_effect=ValueError('unmatched quote')):
            self.assertFalse(self.classify('python Agent/web_tools.py search test'))


if __name__ == '__main__':
    unittest.main()
