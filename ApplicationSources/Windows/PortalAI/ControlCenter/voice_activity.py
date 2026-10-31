"""Bounded thread-safe voice display state; audio samples never enter Tk workers."""
from array import array
import math
import sys
import threading
import time


def pcm_level(data):
    samples = array('h')
    samples.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder != 'little': samples.byteswap()
    if not samples: return 0.0
    values = samples[::max(1, len(samples) // 512)]
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    return min(1.0, math.sqrt(rms / 9000))


class VoiceActivity:
    def __init__(self):
        self._lock = threading.Lock()
        self._phase, self._text = 'listening', 'Listening'
        self._level, self._sample_at = 0.0, 0.0
        self._muted = False

    def phase(self, phase, text=None):
        with self._lock:
            self._phase, self._text = phase, text or phase.capitalize()
            self._level, self._sample_at = 0.0, time.monotonic()

    def level(self, value, *, source='microphone'):
        with self._lock:
            self._level = 0.0 if source == 'microphone' and self._muted else max(0.0, min(1.0, float(value)))
            self._sample_at = time.monotonic()

    def toggle_mute(self):
        with self._lock:
            self._muted = not self._muted
            self._level = 0.0
            return self._muted

    @property
    def muted(self):
        with self._lock: return self._muted

    def snapshot(self):
        with self._lock:
            age = time.monotonic() - self._sample_at
            level = self._level * max(0.0, 1.0 - max(0.0, age - .15) / .4)
            return {'phase': self._phase, 'text': self._text, 'level': level, 'muted': self._muted}
