"""Exercise native presence penalties without loading a model or GPU backend."""
import ctypes as C
import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))


class TokenData(C.Structure):
    _fields_ = [('id', C.c_int32), ('logit', C.c_float), ('p', C.c_float)]


class TokenArray(C.Structure):
    _fields_ = [('data', C.POINTER(TokenData)), ('size', C.c_size_t),
                ('selected', C.c_int64), ('sorted', C.c_bool)]


@unittest.skipUnless(os.name == 'nt', 'Pinned Windows x64 native sampler')
class NativeSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_probe import validate_abi
        folder = ROOT / 'LLM/llamacpp'
        if not (folder / 'llama.dll').is_file():
            raise unittest.SkipTest('Optional pinned native runtime not installed')
        proof = validate_abi()
        for name, digest in proof['libraries'].items():
            with (folder / name).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise RuntimeError('Native runtime differs from ABI proof: ' + name)
        cls.directory = os.add_dll_directory(str(folder))
        cls.lib = C.CDLL(str(folder / 'llama.dll'))
        for name, restype, argtypes in [
            ('llama_sampler_init_penalties', C.c_void_p,
             [C.c_int32, C.c_int32, C.c_float, C.c_float, C.c_float]),
            ('llama_sampler_accept', None, [C.c_void_p, C.c_int32]),
            ('llama_sampler_apply', None, [C.c_void_p, C.POINTER(TokenArray)]),
            ('llama_sampler_free', None, [C.c_void_p]),
        ]:
            function = getattr(cls.lib, name)
            function.restype = restype
            function.argtypes = argtypes

    @classmethod
    def tearDownClass(cls):
        cls.directory.close()

    def logits(self, sampler):
        data = (TokenData * 2)(TokenData(3, 5., 0.), TokenData(4, 2., 0.))
        array = TokenArray(data, len(data), -1, False)
        self.lib.llama_sampler_apply(sampler, C.byref(array))
        return [float(item.logit) for item in data]

    def test_negative_history_is_disabled_in_pinned_runtime(self):
        sampler = self.lib.llama_sampler_init_penalties(8, -1, 1., 0., 1.5)
        self.assertTrue(sampler)
        try:
            self.lib.llama_sampler_accept(sampler, 3)
            self.assertEqual(self.logits(sampler), [5., 2.])
        finally:
            self.lib.llama_sampler_free(sampler)

    def test_positive_history_penalizes_presence_once_and_not_unseen_tokens(self):
        sampler = self.lib.llama_sampler_init_penalties(8, 64, 1., 0., 1.5)
        self.assertTrue(sampler)
        try:
            self.assertEqual(self.logits(sampler), [5., 2.])
            for _ in range(3):
                self.lib.llama_sampler_accept(sampler, 3)
                self.assertEqual(self.logits(sampler), [3.5, 2.])
        finally:
            self.lib.llama_sampler_free(sampler)

    def exercise_generate(self, penalty):
        from native_forward import Forward
        from native_probe import SamplerChainParams
        worker = Forward.__new__(Forward)
        worker.context = 1024
        worker.batch = 64
        worker.ctx = None
        worker.vocab = None
        worker.n_vocab = 8
        worker.names = frozenset()
        worker.tokenize = lambda prompt: [3]  # Prompt tokens must not be penalized.
        worker.decode_chunk = lambda *args: None
        worker.llama_get_memory = lambda context: None
        worker.llama_memory_clear = lambda *args: None
        worker.llama_sampler_chain_default_params = SamplerChainParams
        worker.llama_sampler_chain_init = lambda params: 1
        worker.llama_sampler_chain_add = lambda *args: None
        worker.llama_sampler_init_temp = lambda *args: 2
        worker.llama_sampler_init_top_k = lambda *args: 2
        worker.llama_sampler_init_top_p = lambda *args: 2
        worker.llama_sampler_init_dist = lambda *args: 2
        worker.llama_sampler_free = lambda *args: None
        worker.llama_vocab_is_eog = lambda vocab, token: token == 0
        worker.piece = lambda token: str(token).encode()
        samplers, constructor_args, observed = [], [], []
        def create(*args):
            constructor_args.append(args)
            sampler = self.lib.llama_sampler_init_penalties(*args)
            self.assertTrue(sampler)
            samplers.append(sampler)
            return sampler
        worker.llama_sampler_init_penalties = create
        tokens = iter([3, 3, 0])
        def sample(*args):
            token = next(tokens)
            if samplers:
                observed.append(self.logits(samplers[0]))
                self.lib.llama_sampler_accept(samplers[0], token)
            return token
        worker.llama_sampler_sample = sample
        try:
            with patch('native_forward.require_gpu_unpaused'):
                result = worker.generate('test', seed=1, max_tokens=4, presence_penalty=penalty)
            self.assertEqual(result['token_ids'], [3, 3, 0])
            self.assertEqual(result['finish'], 'stop')
            return constructor_args, observed
        finally:
            for sampler in samplers:
                self.lib.llama_sampler_free(sampler)

    def test_generate_applies_requested_penalty_to_generated_history(self):
        arguments, observed = self.exercise_generate(1.5)
        self.assertEqual(observed, [[5., 2.], [3.5, 2.], [3.5, 2.]])
        self.assertGreaterEqual(arguments[0][1], 4)

    def test_zero_penalty_leaves_small_model_sampling_unchanged(self):
        arguments, observed = self.exercise_generate(0.)
        self.assertEqual(arguments, [])
        self.assertEqual(observed, [])


if __name__ == '__main__':
    unittest.main()
