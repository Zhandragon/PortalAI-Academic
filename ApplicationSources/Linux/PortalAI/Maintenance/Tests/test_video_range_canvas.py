"""Actual FFmpeg splice with a synthetic scaled replacement; no GPU inference."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
from platform_runtime import ffmpeg_path
import video_range_edit_bridge as ranges


class RangeCanvasTests(unittest.TestCase):
    def test_scaled_replacement_keeps_full_source_canvas_cadence_and_retained_content(self):
        with tempfile.TemporaryDirectory(prefix='Portal range canvas ') as temporary:
            root=Path(temporary);source=root/'source.mp4';ffmpeg=ffmpeg_path(ROOT);ffprobe=ffmpeg_path(ROOT,True)
            if not ffmpeg.is_file() or not ffprobe.is_file():self.skipTest('Bundled FFmpeg unavailable')
            def generate(path,size,fps,duration,color):
                subprocess.run([str(ffmpeg),'-v','error','-nostdin','-y','-f','lavfi','-i',
                    f'color=c={color}:size={size}:rate={fps}:duration={duration}','-an','-c:v','libx264',
                    '-threads','1','-pix_fmt','yuv420p',str(path)],capture_output=True,check=True,timeout=30,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            generate(source,'640x360',24,1.5,'blue')
            commands=[]
            def replacement(args):
                commands.append(args)
                output=Path(args[args.index('--output')+1])
                w,h=int(args[args.index('--width')+1]),int(args[args.index('--height')+1])
                generate(output,f'{w}x{h}',int(args[args.index('--fps')+1]),.5,'red')
                return {'files':[str(output)],'backend':'synthetic replacement'}
            with patch.object(ranges,'_root_dir',return_value=root),\
                 patch.object(ranges,'_find_tool',side_effect=lambda name:str(ffprobe if name=='ffprobe' else ffmpeg)),\
                 patch('radeon_edit.uses_radeon',return_value=True),\
                 patch('workload_compatibility.require_workload'),\
                 patch.object(ranges,'_child_ai_tools',side_effect=replacement):
                result=ranges.video_range_edit(str(source),'synthetic red interval',start=.5,end=1.,mode='vace',drop_audio=True)
                output=Path(result['files'][0]);info=ranges._probe(output)
            self.assertEqual((info['width'],info['height'],info['fps']),(640,360,24.))
            self.assertAlmostEqual(info['duration'],1.5,delta=1/24)
            self.assertLessEqual(max(result['generation_resolution']),320)
            self.assertEqual(result['resolution'],[640,360])
            for timestamp,color_channel in ((.25,2),(.75,0),(1.25,2)):
                cp=subprocess.run([str(ffmpeg),'-v','error','-nostdin','-ss',str(timestamp),'-i',str(output),
                    '-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                    capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(len(cp.stdout),3);self.assertGreater(cp.stdout[color_channel],200)


if __name__=='__main__':unittest.main()
