"""Regressions from Nice's live inspect/available_tools command loop."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from account_tool_policy import MEDIA_COMMANDS
from media_tool_api import TOOLS, media_argv
from media_planning import TOOL, MediaPlanning


class MediaCommandRecoveryTests(unittest.TestCase):
    def test_media_schema_excludes_noncommands_and_covers_registered_workers(self):
        media=next(t['function'] for t in TOOLS if t['function']['name']=='media_tool')
        commands=media['parameters']['properties']['command']['enum']
        self.assertEqual(set(commands),set(MEDIA_COMMANDS))
        self.assertNotIn('inspect',commands)
        self.assertNotIn('available_tools',commands)

    def test_inspection_error_names_the_separate_function_and_arguments(self):
        with self.assertRaisesRegex(PermissionError,'media_plan.*"action":"inspect".*"paths"'):
            media_argv(ROOT,'python','inspect',['photo.jpg'])

    def test_discovery_error_explains_loading_and_an_executable_help_route(self):
        with self.assertRaises(PermissionError) as error:
            media_argv(ROOT,'python','available_tools',[])
        text=str(error.exception)
        self.assertIn('separate function, not a command',text)
        self.assertIn('tool_help({"tools":["available_tools"]})',text)
        self.assertIn('"arguments":["--help"]',text)

    def test_missing_reference_scope_cannot_silently_trigger_three_image_research(self):
        schema=TOOL['function']['parameters']['properties']['assessment']
        self.assertIn('reference_scope',schema['required'])
        planner=MediaPlanning('Edit this supplied photo')
        with self.assertRaisesRegex(ValueError,'Choose reference_scope explicitly'):
            planner.call(None,{'action':'assess','assessment':{'understanding':'sufficient'}})
        self.assertIsNone(planner.assessment)


if __name__=='__main__':unittest.main()
