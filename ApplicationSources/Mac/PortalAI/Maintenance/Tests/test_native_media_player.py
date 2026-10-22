"""Synthetic Tk playback controls plus short, silent bundled FFplay evidence."""
import gc
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import wave
import tkinter as tk

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(Path(__file__).parent)]
import native_media_player as media
from tk_fixture_cleanup import finish_tk_fixture


class MediaControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='portal-player-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'synthetic.wav'
        with wave.open(str(self.file),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(b'\0\0'*48000)
        self.app=tk.Tk();self.app.geometry('800x640-10000-10000')
        self.body=tk.Frame(self.app);self.body.pack(fill='both',expand=True)
        self.panel=SimpleNamespace(root=self.root,app=self.app,_check_login=Mock(),_closing=False,
            _thread=threading.Thread,COL={'bg':'#17191c','panel2':'#292c30','text':'#ffffff','muted':'#bbbbbb','gold':'#b88a32'})
        self.player=None

    def tearDown(self):
        if self.player:self.player.close();self.player.widget.destroy()
        self.player=None
        self.assertEqual(finish_tk_fixture(self.app),0)
        self.player=self.app=self.body=self.panel=None;gc.collect()

    def fixture(self):
        with patch.object(media.NativeMediaPlayer,'_probe_duration'):
            self.player=media.NativeMediaPlayer(self.panel,self.body,self.file)
        self.player.probe_thread.join(2);self.player.duration=60
        self.player.timeline.configure(to=60,state='normal');self.app.update()
        return self.player

    def pump(self,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.app.update();time.sleep(.02)

    def test_click_drag_commits_one_exact_seek_on_release(self):
        p=self.fixture();p.proc=Mock();p.proc.poll.return_value=None
        with patch.object(p,'_start') as start:
            left=p.timeline.coords(0)[0];right=p.timeline.coords(60)[0]
            for fraction in (.2,.4,.75):
                p._drag_seek(SimpleNamespace(x=round(left+(right-left)*fraction)))
            self.app.update();start.assert_not_called()
            p._release_seek(None);self.assertEqual(start.call_count,1)
            self.assertAlmostEqual(start.call_args.args[0],45,delta=.2)
        p.proc=None

    def test_status_refresh_does_not_accidentally_restart_playback(self):
        p=self.fixture()
        with patch.object(p,'seek') as seek:
            for value in (1.23,2.57,3.98):p.position=value;p._display();self.app.update()
            self.pump(.4);seek.assert_not_called()

    def test_stop_prevents_delayed_metadata_autoplay_and_queued_seek(self):
        p=self.fixture();p._timeline_key('20');p.stop()
        p.pending.put(('duration',30))
        with patch.object(p,'_start') as start:
            self.pump(.4);start.assert_not_called()
        self.assertIsNone(p.seek_id);self.assertFalse(p.autoplay)

    def test_volume_drag_changes_once_on_release_and_keeps_pause(self):
        p=self.fixture();p.proc=Mock();p.proc.poll.return_value=None;p.paused=True;p.position=12.5;p.volume_drag=True
        with patch.object(p,'_start') as start:
            for value in (30,40,50):p.volume_value.set(value);p._volume_changed(str(value))
            self.pump(.3);start.assert_not_called()
            p._volume_release(None);start.assert_called_once_with(12.5,True)
            self.pump(.3);self.assertEqual(start.call_count,1)
        p.proc=None

    def test_close_cancels_callback_admission_and_late_profile_change(self):
        p=self.fixture();p._timeline_key('20');p.close()
        with patch.object(p,'_start') as start:
            self.pump(.35);p.seek(30);start.assert_not_called()
        self.assertTrue(p.closed);self.assertIsNone(p.poll_id);self.assertIsNone(p.seek_id)
        with self.assertRaisesRegex(RuntimeError,'closed'):p._check()

    def test_finished_clip_discards_late_stats_and_play_restarts_at_zero(self):
        p=self.fixture();p.proc=Mock();p.proc.poll.return_value=0;child=p.proc
        p.pending.put(('exit',(child,0,'')));p.latest_position=(child,59.8)
        self.pump(.15)
        self.assertIsNone(p.proc);self.assertEqual(p.position,60);self.assertEqual(p.status.get(),'Playback finished.')
        with patch.object(p,'_start') as start:
            p.toggle();start.assert_called_once_with(0,False)

    @unittest.skipUnless(os.name=='nt','Actual silent Windows FFplay test')
    def test_actual_silent_player_reports_position_seeks_and_closes(self):
        original_player,original_probe=media.player_command,media.probe_command
        with patch.object(media,'player_command',side_effect=lambda root,path,title,pos,vol,origin=0:original_player(ROOT,path,title,pos,0,origin)), \
             patch.object(media,'probe_command',side_effect=lambda root,path:original_probe(ROOT,path)), \
             patch.dict(os.environ,{'SDL_AUDIODRIVER':'dummy'}):
            self.player=media.NativeMediaPlayer(self.panel,self.body,self.file);p=self.player
            self.pump(1.2)
            self.assertAlmostEqual(p.duration,6,delta=.1);self.assertIsNotNone(p.proc)
            first=p.proc;self.assertIsNone(first.poll());self.assertGreater(p.position,0)
            self.assertNotEqual(p._owned_hwnd(),0)
            p.seek(3);second=p.proc;self.assertIsNot(first,second);self.assertIsNotNone(first.poll())
            self.pump(.9);self.assertGreaterEqual(p.position,3);self.assertLess(p.position,5)
            p.toggle();self.pump(.3);paused=p.position;self.assertTrue(p.paused)
            self.pump(.35);self.assertAlmostEqual(p.position,paused,delta=.15)
            p.close();self.assertIsNotNone(second.poll());self.assertFalse(p.probe_thread.is_alive())
            self.assertIsNone(p.reader);self.assertIsNone(p.proc)

    def test_linux_pause_has_no_suspended_child_to_orphan(self):
        p=self.fixture();p.position=12.5;p.proc=Mock();p.proc.poll.return_value=None;child=p.proc
        with patch.object(media.os,'name','posix'):
            self.assertTrue(p._set_pause(True))
        self.assertTrue(p.paused);self.assertEqual(p.position,12.5);self.assertIsNone(p.proc)
        child.terminate.assert_called_once();child.send_signal.assert_not_called()


class MediaProcessTests(unittest.TestCase):
    def test_parse_actual_ffplay_progress_ignores_logs_and_nan(self):
        self.assertEqual(media.position_from_stats('   3.12 M-A:  0.000 fd=0'),3.12)
        self.assertEqual(media.position_from_stats('  4.28 A-V: -.003 fd=0'),4.28)
        self.assertIsNone(media.position_from_stats('    nan M-V: 0'))
        self.assertIsNone(media.position_from_stats('Input #0, wav, from fixture'))
        self.assertEqual(media.time_text(3671),'1:01:11')

    def test_seek_drops_prior_keyframes_and_normalizes_container_start_time(self):
        with patch.object(media.os,'name','nt'):
            command=media.player_command(ROOT,ROOT/'synthetic.mp4','fixture',3,70,5)
        self.assertEqual(command[command.index('-ss')+1],'3.000')
        self.assertEqual(command[command.index('-vf')+1],'trim=start=8.000000')
        self.assertEqual(command[command.index('-af')+1],'atrim=start=8.000000')


if __name__=='__main__':unittest.main()
