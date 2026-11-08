"""Scientific file cards retain the private-reference and explicit-open boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from native_chat import NativeChat


class ScienceOutputCardTests(unittest.TestCase):
    def test_scientific_outputs_get_cards_without_running_a_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[root/name for name in ('world.html','scene.json','assembly.svg','sequence.fasta','part.step')]
            for path in paths:path.write_text('fixture')
            panel=Mock(root=root)
            panel._resolve_private_reference.side_effect=lambda value:Path(value)
            rows=NativeChat.prepare_media_from_tool_result(panel,json.dumps({'files':list(map(str,paths)),'data':{'file':str(paths[0])}}))
            self.assertEqual(len(rows),5)
            panel.make_thumbnail.assert_not_called()
            panel._check_login.assert_called_once()
            self.assertEqual({Path(row['path']).name for row in rows},{p.name for p in paths})

    def test_denied_reference_does_not_hide_a_later_permitted_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);good=root/'result.csv';good.write_text('x,y\n1,2')
            executable=root/'run.exe';executable.write_text('not executed')
            directory=root/'folder.json';directory.mkdir()
            panel=Mock(root=root)
            def resolve(value):
                if value=='other-account.svg':raise PermissionError('foreign account')
                return Path(value)
            panel._resolve_private_reference.side_effect=resolve
            rows=NativeChat.prepare_media_from_tool_result(panel,json.dumps({'files':['other-account.svg',str(executable),str(directory),str(good)]}))
            self.assertEqual([Path(row['path']).name for row in rows],['result.csv'])
            panel.make_thumbnail.assert_not_called()


if __name__=='__main__':unittest.main()
