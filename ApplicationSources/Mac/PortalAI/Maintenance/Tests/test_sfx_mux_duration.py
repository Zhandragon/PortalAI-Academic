"""Real bundled FFmpeg mux regressions; generated fixtures, never model inference."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from platform_runtime import ffmpeg_path
from sfx_bridge import SfxBridge


class SfxMuxDurationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal SFX duration ')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.ffmpeg=ffmpeg_path(ROOT);self.ffprobe=ffmpeg_path(ROOT,True)
        if not self.ffmpeg.is_file() or not self.ffprobe.is_file():self.skipTest('Bundled FFmpeg unavailable')
        self.bridge=SfxBridge.__new__(SfxBridge);self.bridge.root=self.root
        self.bridge._ffmpeg=lambda:str(self.ffmpeg);self.bridge._ffprobe=lambda:str(self.ffprobe)
        self.sfx=self.root/'sfx.wav'
        self.run_ffmpeg('-f','lavfi','-i','sine=frequency=660:duration=0.4','-c:a','pcm_s16le',str(self.sfx))

    def run_ffmpeg(self,*args):
        subprocess.run([str(self.ffmpeg),'-v','error','-nostdin','-y','-threads','1',*args],
                       check=True,capture_output=True,timeout=30,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def source(self, audio=False):
        source=self.root/'source.mp4'
        args=['-f','lavfi','-i','color=c=blue:size=64x64:rate=20:duration=1.6']
        if audio:args+=['-f','lavfi','-i','sine=frequency=220:duration=0.8']
        args+=['-map','0:v','-c:v','libx264','-threads','1','-pix_fmt','yuv420p']
        if audio:args+=['-map','1:a','-c:a','aac']
        self.run_ffmpeg(*args,str(source));return source

    def mux(self,source,replace=False):
        destination=self.root/'result.mp4'
        self.bridge._mux_video(source,self.sfx,destination,source_volume=1.,sfx_volume=.7,replace_audio=replace)
        actual,fps=self.bridge._video_timing(destination)
        self.assertAlmostEqual(actual,1.6,delta=1/fps)
        cp=subprocess.run([str(self.ffprobe),'-v','error','-count_frames','-show_streams','-of','json',str(destination)],
            capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        streams=json.loads(cp.stdout)['streams']
        video=next(row for row in streams if row['codec_type']=='video')
        audio=next(row for row in streams if row['codec_type']=='audio')
        self.assertEqual(int(video['nb_read_frames']),32)
        self.assertAlmostEqual(float(audio['duration']),1.6,delta=.05)

    def test_short_sfx_does_not_cut_silent_source(self):self.mux(self.source())
    def test_replacement_audio_preserves_complete_video(self):self.mux(self.source(audio=True),replace=True)
    def test_short_source_audio_and_short_sfx_pad_to_visual_duration(self):self.mux(self.source(audio=True))
    def test_long_sfx_is_bounded_to_video_without_extending_it(self):
        self.run_ffmpeg('-f','lavfi','-i','sine=frequency=660:duration=2.4','-c:a','pcm_s16le',str(self.sfx))
        self.mux(self.source(),replace=True)

    def test_truncated_result_is_rejected_instead_of_reported_success(self):
        source=self.source()
        with patch.object(self.bridge,'_video_timing',side_effect=[(1.6,20.),(.4,20.)]):
            with self.assertRaisesRegex(RuntimeError,'changed the source video duration'):
                self.bridge._mux_video(source,self.sfx,self.root/'bad.mp4',source_volume=1,sfx_volume=1,replace_audio=True)


if __name__=='__main__':unittest.main()
