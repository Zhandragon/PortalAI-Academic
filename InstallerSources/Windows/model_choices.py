"""Explicit, separately licensed model choices for release installers.

This module performs no downloads and never accepts terms on the user's behalf.
The build step adds the same review metadata to every edition's manifest.
"""
import copy
import hashlib
import json
from urllib.parse import urlsplit


POLICIES = {
    'text-small': ('Apache-2.0', 'Suggested small chat models. Preserve license and attribution notices.', 'https://huggingface.co/Qwen/Qwen3-1.7B'),
    'text-4b': ('Apache-2.0', 'Suggested chat models. Preserve license and attribution notices.', 'https://huggingface.co/Qwen/Qwen3-4B'),
    'vision-2b': ('Apache-2.0', 'Optional vision models and matching projectors; preserve notices.', 'https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct'),
    'vision-4b': ('Apache-2.0', 'Optional vision models and matching projectors; preserve notices.', 'https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct'),
    'musicgen-cpu-models': ('CC-BY-NC-4.0', 'NONCOMMERCIAL weights; attribution required. Optional music workflow.', 'https://huggingface.co/facebook/musicgen-small'),
    'mmaudio-models': ('CC-BY-NC-4.0 + Apple research-only + dependencies', 'RESEARCH-ONLY DEPENDENCY: the included Apple DFN5B-CLIP weights permit noncommercial scientific research only and exclude product development or use in commercial products/services. Personal use alone is not sufficient. MMAudio weights are CC-BY-NC-4.0; the vocoder and synchronization weights have separate terms. Review https://huggingface.co/apple/DFN5B-CLIP-ViT-H-14-384/blob/main/LICENSE before choosing this workflow.', 'https://huggingface.co/apple/DFN5B-CLIP-ViT-H-14-384/blob/main/LICENSE'),
    'mmaudio-extra-models-optional': ('CC-BY-NC-4.0 + dependency licenses', 'NONCOMMERCIAL MMAudio weights; optional variants and supporting models.', 'https://huggingface.co/hkchengrex/MMAudio'),
    'coding-swift-27b': ('Swift Open License 1.0 + Apache-2.0', 'Commercial-use conditions include a US$1 million affiliated-revenue threshold. Review derivative and base-model notices.', 'https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27b/blob/main/LICENSE'),
    'sd15-models': ('CreativeML OpenRAIL-M', 'Commercial use is permitted subject to the license, including use restrictions and downstream notices.', 'https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5'),
    'flux-model-subset-optional': ('Mixed: Apache-2.0 / FLUX Non-Commercial', 'Includes restricted derivatives. Review the exact file and base-model terms, commercial-use permission and filtering/output-review obligations.', 'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B/blob/main/LICENSE.md'),
    'comfy-models-optional': ('Mixed model and adapter licenses', 'Includes FLUX Non-Commercial weights and separately licensed video models/LoRAs. Do not assume one license covers this collection.', 'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B/blob/main/LICENSE.md'),
    'shared-image-video-models': ('Separate encoder and VAE licenses', 'Shared supporting models. Review each publisher and the license of the workflow using them.', 'https://huggingface.co/Comfy-Org/flux2-klein-9B'),
    'whisper-base-model': ('MIT', 'Optional speech-recognition weights; preserve the publisher license notice.', 'https://huggingface.co/Systran/faster-whisper-base'),
    'ace-step-models': ('MIT + Apache-2.0 dependencies', 'Optional music model, VAE and Qwen embedding assets. Preserve each publisher notice.', 'https://huggingface.co/ACE-Step/Ace-Step1.5'),
    'ace-language-model-optional': ('MIT', 'Optional ACE-Step language model; preserve publisher notices.', 'https://huggingface.co/ACE-Step/Ace-Step1.5'),
    'ace-step-extra-models-optional': ('MIT', 'Optional ACE-Step configuration; preserve publisher notices.', 'https://huggingface.co/ACE-Step/Ace-Step1.5'),
    'qwen-tts-models': ('Apache-2.0', 'Optional speech models. Preserve notices; obtain permission for any voice or likeness you use.', 'https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base'),
    'sam2-models': ('Apache-2.0', 'Optional segmentation, grounding and supporting text models; preserve individual notices.', 'https://huggingface.co/facebook/sam2.1-hiera-large'),
    'musetalk-models': ('MIT + separately licensed dependencies', 'MuseTalk is MIT; Whisper, the VAE, pose, face-parsing and synchronization weights have separate terms. Review every source; the workflow label does not grant rights to every dependency.', 'https://huggingface.co/TMElyralab/MuseTalk'),
    'music-understanding-models-optional': ('Apache-2.0', 'Optional MOSS and CLAP music-understanding models; preserve publisher notices.', 'https://huggingface.co/OpenMOSS-Team/MOSS-Music-8B-Instruct'),
    'instruction-edit-models-optional': ('MIT + Stable Diffusion base-model terms', 'The publisher lists MIT; review the base model and encoder/VAE licenses as well, including applicable use restrictions.', 'https://huggingface.co/timbrooks/instruct-pix2pix'),
    'piper-voice': ('Voice model cards + GPL-3.0 runtime', 'The ljspeech and joe cards identify public-domain/CC0 training data. Review the voice cards and parent-voice provenance; dataset terms alone do not establish every model right. The Piper runtime has its own GPL terms.', 'https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US'),
    'wan-model-subset-optional': ('Apache-2.0 + CreativeML OpenRAIL-M derivative', 'The standard Wan example uses Apache-2.0; the separate NSFW-API derivative lists OpenRAIL-M use restrictions. Review the encoder and derivative terms separately.', 'https://huggingface.co/NSFW-API/NSFW_Wan_1.3b'),
    'vace-small-models-optional': ('Apache-2.0', 'Optional Wan VACE model; preserve publisher notices. Shared encoder/VAE dependencies are reviewed separately.', 'https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged'),
    'demucs-model': ('MIT', 'Optional HTDemucs source-separation model; preserve the publisher license and notices.', 'https://github.com/facebookresearch/demucs'),
    'protein-runtime': ('MIT', 'Optional ProteinMPNN code and example weights for protein design. Preserve publisher notices and review the suitability of generated scientific results.', 'https://github.com/dauparas/ProteinMPNN/blob/main/LICENSE'),
}

# Explicit inventory, rather than a filename extension heuristic: Python .pth
# files and executable firmware .bin files are not user-selected model weights.
OTHER_MODEL_COMPONENTS = frozenset((
    'piper-voice', 'whisper-base-model', 'ace-step-models',
    'ace-language-model-optional', 'qwen-tts-models', 'musetalk-models',
    'sam2-models', 'wan-model-subset-optional',
    'instruction-edit-models-optional', 'vace-small-models-optional',
    'demucs-model', 'music-understanding-models-optional',
))


def digest(review):
    return hashlib.sha256(json.dumps(review, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply_policy(manifest):
    """Keep artifact pins intact; make named model groups explicit opt-ins."""
    result = copy.deepcopy(manifest)
    for component in result['components']:
        key = component['id']
        if key not in POLICIES and key not in OTHER_MODEL_COMPONENTS:
            continue
        sources = sorted({a['url'] for a in component.get('artifacts', []) if a.get('url')})
        license_name, restrictions, license_url = POLICIES.get(key, (
            'See individual publisher licenses',
            'Optional, suggested/supported assets. Review the licenses of every model and dependency before choosing this download.',
            sources[0] if sources else '',
        ))
        review = {'license': license_name, 'restrictions': restrictions,
                  'license_url': license_url, 'sources': sources,
                  'artifacts': [{'id': a['id'], 'sha256': a['sha256'], 'bytes': a['bytes']}
                                for a in component.get('artifacts', [])]}
        component['required'] = False
        component['model_choice'] = {**review, 'review_digest': digest(review)}
    result['model_choice_policy'] = 1
    return result


def validate_consent(manifest, chosen, selected, consent):
    """A dependency cannot silently authorize an extra model download."""
    if manifest.get('model_choice_policy') != 1:
        return
    if consent is None and not any(c.get('model_choice') for c in chosen):
        return
    if not isinstance(consent, dict):
        raise ValueError('Review the selected model licenses before installing.')
    selected = set(selected)
    for component in chosen:
        review = component.get('model_choice')
        if not review:
            continue
        expected = digest({k: v for k, v in review.items() if k != 'review_digest'})
        if review.get('review_digest') != expected:
            raise ValueError('Model license review metadata changed: ' + component['id'])
        if component.get('required'):
            raise ValueError('Model downloads must be optional: ' + component['id'])
        if component['id'] not in selected or consent.get(component['id']) != expected:
            raise ValueError('Select and review the model and its dependencies explicitly: ' + component['id'])


def validate_custom_request(request, *, academic=False):
    """Validate a different compatible GGUF, never a mirror masquerading as a pin.

File-level GGUF checks and backend admission are additional steps. Arbitrary
Python/pickle checkpoints, repository code and installers are not accepted.
"""
    if not isinstance(request, dict):
        raise ValueError('Custom model details must be an object')
    required = {'url', 'sha256', 'bytes', 'label', 'license_url', 'variant', 'accepted'}
    if set(request) != required or request.get('accepted') is not True:
        raise ValueError('Review and acknowledge the custom model license and source')
    for name in ('url', 'license_url'):
        value = request[name]
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError('Invalid model URL')
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.fragment or any(c.isspace() for c in value)):
            raise ValueError('Use a public HTTPS URL without credentials or fragments')
    if not urlsplit(request['url']).path.lower().endswith('.gguf'):
        raise ValueError('Choose a direct GGUF file URL; repository pages and executable model code are not supported')
    pin = request['sha256']
    if not isinstance(pin, str) or len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
        raise ValueError('Provide the publisher SHA-256 for the exact custom model')
    if type(request['bytes']) is not int or not 1024 <= request['bytes'] <= 512 * 1024**3:
        raise ValueError('Provide the exact model size in bytes (at most 512 GiB)')
    if not isinstance(request['label'], str) or not request['label'].strip() or len(request['label']) > 100 or any(ord(c) < 32 for c in request['label']):
        raise ValueError('Provide a short model name without control characters')
    if request['variant'] not in ('standard', 'uncensored') or (academic and request['variant'] != 'standard'):
        raise ValueError('Academic accepts standard models only')
    return dict(request)


def with_custom_model(manifest, request):
    """Add a separately pinned file and review record, never replace a known pin."""
    if request is None:
        return manifest, None
    request = validate_custom_request(request, academic=manifest.get('upgrade', {}).get('edition') == 'Academic')
    if manifest.get('upgrade', {}).get('edition') == 'Academic':
        exclusions = manifest.get('academic_custom_model_exclusions')
        if not isinstance(exclusions, list):
            raise ValueError('This Academic package has no custom-model admission policy')
        if request['sha256'] in exclusions or any(word in (request['url']+' '+request['label']).casefold()
                                                for word in ('abliterat', 'uncensor')):
            raise ValueError('This model is excluded from Academic')
    result = copy.deepcopy(manifest)
    key = 'custom-' + request['sha256']
    dest = 'PortalAI Windows/LLM/custom/' + request['sha256'] + '.gguf'
    row = dict(dest=dest, bytes=request['bytes'], sha256=request['sha256'])
    artifact = dict(id=key, url=request['url'], bytes=request['bytes'], sha256=request['sha256'],
                    format='file', members=[row], custom_gguf=True)
    if any(c['id'] == key for c in result['components']):
        raise ValueError('Duplicate custom model')
    result['components'].append(dict(id=key, label=request['label'], required=False, artifacts=[artifact]))
    result.setdefault('generated_receipts', []).append({
        'dest': 'PortalAI Windows/Maintenance/Imports/' + key + '.json',
        'components': [key], 'files': [row],
        'data': {'schema': 1, 'kind': 'portalai-custom-model', 'request': request,
                 'path': 'LLM/custom/' + request['sha256'] + '.gguf'}})
    return result, key
