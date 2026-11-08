"""Stop hands-free during restoration, concurrent capture teardown, and Tk liveness."""
from pathlib import Path
import sys, threading, time, unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Maintenance/Tests')]
from voice_echo import EchoCapture
from chat_voice import VoiceIO
from writer_jobs import WriterJobs
import test_chat_voice as voice_tests
from native_chat import WindowsWaveInStream
from types import SimpleNamespace


class CaptureCloseTests(unittest.TestCase):
    def test_winmm_close_waits_for_native_buffer_requeue(self):
        stream=WindowsWaveInStream.__new__(WindowsWaveInStream)
        stream.closed=False;stream._io_lock=threading.RLock();stream.handle=7
        stream.ctypes=Mock();stream.ctypes.string_at.return_value=b'audio'
        stream.headers=[SimpleNamespace(dwFlags=stream.WHDR_DONE,dwBytesRecorded=5,lpData=1)]
        stream.winmm=Mock();stream.winmm.waveInUnprepareHeader.return_value=0
        entered=threading.Event();release=threading.Event()
        def add(*args):entered.set();release.wait(3);return 0
        stream.winmm.waveInAddBuffer.side_effect=add
        reader=threading.Thread(target=stream.read_chunk);closer=threading.Thread(target=stream.close)
        reader.start();self.assertTrue(entered.wait(1));closer.start()
        try:
            time.sleep(.05);stream.winmm.waveInReset.assert_not_called()
        finally:
            release.set();reader.join(2);closer.join(2)
        self.assertFalse(reader.is_alive() or closer.is_alive())
        stream.close();stream.winmm.waveInClose.assert_called_once()

    def test_two_closers_release_job_and_pipes_once(self):
        capture=EchoCapture.__new__(EchoCapture)
        capture.closed=threading.Event();capture.condition=threading.Condition()
        capture._close_lock=threading.Lock();capture._close_done=False
        entered=threading.Event();release=threading.Event();job=Mock()
        job.close.side_effect=lambda:(entered.set(),release.wait(3))
        capture.job=job;capture.proc=Mock();capture.proc.poll.return_value=0
        for pipe in (capture.proc.stdin,capture.proc.stdout,capture.proc.stderr):pipe.closed=False
        a=threading.Thread(target=capture.close);b=threading.Thread(target=capture.close)
        a.start();self.assertTrue(entered.wait(1));b.start()
        release.set();a.join(2);b.join(2)
        self.assertFalse(a.is_alive() or b.is_alive());job.close.assert_called_once()
        capture.proc.wait.assert_called_once()
        for pipe in (capture.proc.stdin,capture.proc.stdout,capture.proc.stderr):pipe.close.assert_called_once()
        capture.close();job.close.assert_called_once()


class VoiceStopTkTests(unittest.TestCase):
    setUp=voice_tests.VoiceUITests.setUp
    prepare=voice_tests.VoiceUITests.prepare
    pump=voice_tests.VoiceUITests.pump

    def test_logout_registers_audio_cleanup_before_closing_writer_admission(self):
        p=self.prepare();p._writer_jobs=WriterJobs();p._conversation_io=VoiceIO(ROOT,lambda:None)
        voice=p._conversation_io;release=threading.Event()
        capture=Mock();p.conversation_capture_stream=capture
        def capture_loop():voice.cancelled.wait(3);release.wait(3);capture.close()
        p.conversation_thread=p._thread(target=capture_loop,daemon=True);p.conversation_thread.start()
        p.mic_stream=p.mic_proc=None;p.mic_stop_event=threading.Event()
        p.memory=Mock();p._stop_embedded_media=Mock();p.tool_runtime=Mock();p.tool_runtime._workspace_cleanup_errors=[]
        try:
            with patch('command_palette.close'):p.shutdown()
            self.assertTrue(voice.cancelled.is_set())
            self.assertIsNotNone(p._conversation_cleanup)
            with self.assertRaises(RuntimeError):p._thread(target=lambda:None).start()
        finally:
            release.set();p.wait_audio_release();p.conversation_thread.join(3)
        self.assertTrue(p.wait_for_writers(3)['stopped'])

    def test_end_voice_then_component_audio_release_keeps_tk_responsive(self):
        p=self.prepare();p._writer_jobs=WriterJobs()
        voice=p._conversation_io=VoiceIO(ROOT,lambda:None)
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        prepared=Mock();prepared.close.side_effect=lambda:(entered.set(),release.wait(4))
        voice._prepared_voice=prepared
        capture=Mock();p.conversation_capture_stream=capture
        def conversation():
            voice.cancelled.wait(3)
            # Model restoration is still completing after playback ended.
            release.wait(4);capture.close();finished.set()
        p.conversation_thread=p._thread(target=conversation,daemon=True)
        p.conversation_thread.start()
        p.mic_stream=p.mic_proc=None;p.mic_stop_event=threading.Event()
        tick=[]
        self.app.after(1,lambda:tick.append('responsive'))
        try:
            started=time.monotonic();p.stop_conversation_mode()
            self.assertLess(time.monotonic()-started,.25)
            self.assertTrue(voice.cancelled.is_set());self.assertFalse(p.conversation_active.is_set())
            self.assertTrue(entered.wait(1))
            # This is the audio-release operation of Stop all components.
            p.release_audio_capture();p.stop_conversation_mode()
            deadline=time.monotonic()+1
            with patch('voice_layout.sync_voice_view'):
                while not tick and time.monotonic()<deadline:self.pump();time.sleep(.01)
            self.assertEqual(tick,['responsive']);self.assertTrue(self.app.winfo_exists())
        finally:
            release.set();p.wait_audio_release();p.conversation_thread.join(3)
            p._writer_jobs.close();self.assertTrue(p._writer_jobs.wait(3)['stopped'])
        self.assertTrue(finished.is_set());prepared.close.assert_called_once()


if __name__=='__main__':unittest.main()
