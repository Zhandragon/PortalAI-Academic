"""Real tiny FFmpeg fixtures with synthetic generation, never model inference."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
from platform_runtime import ffmpeg_path
import video_range_edit_bridge as ranges


class RegenerationTimingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal regen ');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.ffmpeg=ffmpeg_path(ROOT);self.ffprobe=ffmpeg_path(ROOT,True)
        if not self.ffmpeg.is_file() or not self.ffprobe.is_file():self.skipTest('Bundled FFmpeg required')
        self.source=self.root/'source.mp4';self.generate(self.source,640,360,24,1.5,'blue')
        self.calls=[]

    def run_ffmpeg(self,args):
        return subprocess.run([str(self.ffmpeg),'-v','error','-nostdin','-y',*map(str,args)],
            check=True,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def generate(self,path,w,h,fps,duration,color):
        self.run_ffmpeg(['-f','lavfi','-i',f'color=c={color}:size={w}x{h}:rate={fps}:duration={duration}',
            '-an','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',path])

    def child(self,args):
        self.calls.append(args)
        def value(flag):return int(args[args.index(flag)+1])
        self.assertEqual(args[0],'video');self.assertTrue(Path(args[1]).is_file())
        self.assertLessEqual(value('--length'),17)
        generated=self.root/f'child_{len(self.calls)}.mp4'
        self.generate(generated,value('--width'),value('--height'),value('--fps'),
                      value('--length')/value('--fps'),'red')
        return {'files':[str(generated)],'conditioning':'reference-image','backend':'synthetic'}

    def render(self,**kwargs):
        with patch.object(ranges,'_root_dir',return_value=self.root),\
             patch.object(ranges,'_find_tool',side_effect=lambda name:str(self.ffprobe if name=='ffprobe' else self.ffmpeg)),\
             patch('radeon_edit.uses_radeon',return_value=True),patch('workload_compatibility.require_workload'),\
             patch.object(ranges,'_child_ai_tools',side_effect=self.child):
            result=ranges.video_range_edit(str(self.source),'new red scene',drop_audio=True,**kwargs)
            info=ranges._probe(Path(result['files'][0]))
        self.assertEqual((info['width'],info['height'],info['fps']),(640,360,24.))
        self.assertGreaterEqual(info['duration']+1e-6,result['output_duration_seconds'])
        self.assertLess(info['duration']-result['output_duration_seconds'],1/24+.001)
        self.assertEqual(result['mode'],'regenerate');self.assertGreater(len(self.calls),1)
        self.assertLess(abs(sum(stage['output_seconds'] for stage in result['child_stages'])-3.07),1/24)
        return result

    def color(self,path,timestamp):
        result=self.run_ffmpeg(['-ss',timestamp,'-i',path,'-frames:v','1','-vf','scale=1:1',
                               '-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
        self.assertEqual(len(result.stdout),3);return result.stdout

    def test_append_retains_original_and_full_requested_extension_across_chunks(self):
        result=self.render(append=3.07,mode='auto')
        self.assertTrue(result['append_only']);self.assertEqual(result['output_duration_seconds'],4.57)
        output=result['files'][0]
        self.assertGreater(self.color(output,.5)[2],200);self.assertGreater(self.color(output,4.4)[0],200)

    def test_duration_changing_tail_regenerates_instead_of_silently_editing(self):
        result=self.render(start=.5,end=1.5,duration=3.07,mode='auto')
        self.assertFalse(result['append_only']);self.assertEqual(result['output_duration_seconds'],3.57)
        self.assertGreater(self.color(result['files'][0],.25)[2],200)

    def test_explicit_reference_is_used_for_first_chunk(self):
        image=self.root/'reference.png'
        self.run_ffmpeg(['-i',self.source,'-frames:v','1',image])
        self.render(append=3.07,mode='regenerate',reference_image=str(image))
        self.assertEqual(Path(self.calls[0][1]),image)
        self.assertNotEqual(Path(self.calls[1][1]),image)

    def test_continuation_anchor_is_exact_last_frame_not_first_of_tail_window(self):
        short=self.root/'last-frame.mp4';frame=self.root/'last.png'
        self.run_ffmpeg(['-f','lavfi','-i','color=c=blue:size=32x32:rate=20:duration=0.35',
                        '-f','lavfi','-i','color=c=red:size=32x32:rate=20:duration=0.10',
                        '-f','lavfi','-i','color=c=lime:size=32x32:rate=20:duration=0.05',
                        '-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]',
                        '-map','[out]','-c:v','libx264','-threads','1',short])
        with patch.object(ranges,'_find_tool',return_value=str(self.ffmpeg)):
            ranges._extract_last_frame(short,frame)
        self.assertGreater(self.color(frame,0)[1],200)


if __name__=='__main__':unittest.main()
