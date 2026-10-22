"""Only registered argv media routes are admitted; no shell or account access."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from account_tool_policy import registered_media_argv, MEDIA_COMMANDS


class AccountMediaCommandsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.boot=self.root/'Runtime/python.exe'

    def test_registered_range_and_sound_commands_preserve_literal_arguments(self):
        for command,expected in (
            ('python Agent/ai_tools.py video-range-edit "User Folder/clip.mp4" "make it sunny" --start 1 --end 3 --mode vace',
             ['video-range-edit','User Folder/clip.mp4','make it sunny','--start','1','--end','3','--mode','vace']),
            ('python Agent/ai_tools.py sound-video "Outputs/clip.mp4" --sfx "Outputs/water.flac" --output "Outputs/mixed.mp4"',
             ['sound-video','Outputs/clip.mp4','--sfx','Outputs/water.flac','--output','Outputs/mixed.mp4'])):
            argv=registered_media_argv(command,self.root,self.boot)
            self.assertEqual(argv,[str(self.boot),str(self.root/'Agent/ai_tools.py'),*expected])

    def test_no_shell_chains_python_flags_or_other_script_can_enter_added_routes(self):
        for command in ('python Agent/ai_tools.py sound-video a --sfx b & whoami',
                        'python -c "print(1)" video-range-edit a',
                        'python Agent/other.py video-range-edit a',
                        'cmd /c python Agent/ai_tools.py sound-video a --sfx b',
                        'python Agent/ai_tools.py video-range-edit a\nwhoami'):
            with self.assertRaises(PermissionError):registered_media_argv(command,self.root,self.boot)

    def test_unreviewed_endpoint_and_service_commands_remain_denied(self):
        for command in ('video-understand','video-analyze','service','cancel'):
            self.assertNotIn(command,MEDIA_COMMANDS)
            with self.assertRaises(PermissionError):
                registered_media_argv('python Agent/ai_tools.py '+command+' anything',self.root,self.boot)


if __name__=='__main__':unittest.main()
