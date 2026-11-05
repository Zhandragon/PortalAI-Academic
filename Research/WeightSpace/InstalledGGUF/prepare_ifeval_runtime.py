"""Prepare only the portable English tokenizer data needed by pinned IFEval.

Uses the already installed same-ABI package layer; no pip, host Python changes,
extra LLMs, or full NLTK corpus download. Existing files are never overwritten.
"""
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))
from experiment import atomic_json, sha, space


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'PortalAI-portable-evaluator-preparation'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Source exceeds the fixed download limit')
    return data


def main():
    destination = LAB / 'final-benchmarks/IFEval/portable-runtime'
    assert not destination.exists(), 'Existing evaluator data requires review.'
    packages = ROOT.parent / 'Utilities/Portable Abliterator/runtime/Lib/site-packages'
    sys.path.insert(0, str(packages))
    import nltk
    import langdetect
    import immutabledict
    import absl
    modules = (nltk, langdetect, immutabledict, absl)
    assert all(Path(module.__file__).resolve().is_relative_to(packages.resolve()) for module in modules)
    revision = json.loads(fetch('https://api.github.com/repos/nltk/nltk_data/commits/gh-pages', 2 * 1024**2))['sha']
    assert len(revision) == 40 and all(character in '0123456789abcdef' for character in revision)
    prefix = 'https://raw.githubusercontent.com/nltk/nltk_data/' + revision + '/'
    data = fetch(prefix + 'packages/tokenizers/punkt_tab.zip', 8 * 1024**2)
    space(LAB, len(data) + 4 * 1024**2)
    destination.mkdir()
    archive = destination / 'punkt_tab.zip'
    archive.write_bytes(data)
    expected = {'collocations.tab', 'sent_starters.txt', 'abbrev_types.txt', 'ortho_context.tab'}
    extracted = {}
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name in sorted(expected):
            source = 'punkt_tab/english/' + name
            info = bundle.getinfo(source)
            assert info.file_size <= 2 * 1024**2
            target = destination / 'nltk_data/tokenizers' / source
            target.parent.mkdir(parents=True, exist_ok=True)
            assert target.resolve().is_relative_to(destination.resolve())
            with target.open('xb') as stream:
                stream.write(bundle.read(source))
            extracted[str(target.relative_to(destination))] = {'bytes': target.stat().st_size, 'sha256': sha(target)}
    nltk.data.path[:] = [str(destination / 'nltk_data')]
    assert nltk.sent_tokenize('One sentence. A second sentence!') == ['One sentence.', 'A second sentence!']
    assert nltk.word_tokenize('A short test.') == ['A', 'short', 'test', '.']
    result = {'passed': True, 'source_repository': 'nltk/nltk_data', 'revision': revision,
              'source_url': prefix + 'packages/tokenizers/punkt_tab.zip',
              'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size,
              'english_files': extracted, 'nltk_version': nltk.__version__,
              'existing_portable_modules': {module.__name__: {'relative_file': str(Path(module.__file__).relative_to(ROOT.parent)),
                                                           'sha256': sha(Path(module.__file__))} for module in modules},
              'new_python_packages_installed': False, 'host_data_used': False,
              'new_llm_weights_downloaded': False,
              'tests': ['English sentence tokenization', 'English word tokenization']}
    atomic_json(destination / 'PROVENANCE.json', result)
    print(json.dumps({'portable_ifeval_tokenizer_ready': True, 'downloaded_bytes': len(data),
                      'extracted_english_bytes': sum(row['bytes'] for row in extracted.values())}), flush=True)


if __name__ == '__main__':
    main()
