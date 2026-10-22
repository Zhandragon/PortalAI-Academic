"""Small structured media interface over the existing registered CLI workers."""
from account_tool_policy import MEDIA_COMMANDS


def capabilities(command=None):
    from dialogue_timing import capability
    return [capability()] if command in (None, '', 'all', 'media_tool', 'dialogue-video') else []


def variant_catalog(root, command=None, *, full=False):
    from model_variants import catalog
    if command is not None and not isinstance(command, str):
        raise ValueError('Catalog command must be a string')
    if command is not None:command = command.strip() or None
    command = {'generate_image':'image', 'media_tool':None, 'all':None}.get(command, command)
    try:
        result = catalog(command, root=root)
    except ValueError:
        if command not in MEDIA_COMMANDS: raise
        result = catalog(root=root)
        result['models'] = []  # Registered utility with no model variant.
    if not full:
        result['models'] = [{key: row[key] for key in ('id','tools','family','status','filtering','standard','uncensored') if key in row}
                            for row in result['models']]
        for row in result['models']:
            for key in ('standard','uncensored'):
                if key in row:row[key] = bool(row[key])
            row.pop('filtering',None)
        result = {key: value for key,value in result.items()
                  if key in ('revision','default','media_default','models')}
    return result


def catalog_response(root, command=None, detail='summary'):
    """One requested tool should not return every command and full weight metadata."""
    import json
    from runtime_policy import load_effective_policy
    from model_preferences import personal
    from tool_contracts import execution_help
    if detail not in ('summary','full'):
        raise ValueError('detail must be summary or full')
    variants = variant_catalog(root, command, full=detail=='full')
    command = command.strip() if isinstance(command,str) else command
    command = {'generate_image':'image', 'all':None, 'media_tool':None, '':None}.get(command,command)
    policy = load_effective_policy(root); defaults = personal(policy)['media']
    result = {'execution_help': execution_help(command), 'execution_help_complete': True,
              'commands': [command] if command else sorted(MEDIA_COMMANDS),
              'chat_variant': policy.get('variant_preference','standard'),
              'media_variant': defaults['media_variant'], 'media_defaults': defaults,
              'variants': variants, 'detail': detail}
    if detail == 'full':result['capabilities'] = capabilities(command)
    if not result['execution_help']:
        del result['execution_help'];del result['execution_help_complete']
        result['usage'] = 'media_tool(command=..., arguments=[...]); use --help only for an unknown argument. detail=full gives model metadata.'
    if command == 'science':
        result['usage'] = 'science(operation="help", input={}); biology.help and science.extensions give focused schemas.'
    return json.dumps(result,ensure_ascii=False,separators=(',',':'))


def image_arguments(args):
    allowed = {'prompt', 'negative', 'variant', 'profile', 'override_saved_profile', 'width', 'height', 'seed', 'steps'}
    if not isinstance(args, dict) or set(args) - allowed:
        raise ValueError('Unknown generate_image argument')
    prompt = args.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000 or '\x00' in prompt:
        raise ValueError('A nonempty image prompt is required (at most 16000 characters)')
    variant = args.get('variant', 'default')
    if variant not in ('default', 'standard', 'uncensored'):
        raise ValueError('Variant must be default, standard or uncensored')
    profile = args.get('profile', 'auto')
    if profile not in ('auto', 'sd15', 'flux', 'klein4'):
        raise ValueError('Profile must be auto, sd15, flux or klein4')
    override = args.get('override_saved_profile', False)
    if type(override) is not bool or override and 'profile' not in args:
        raise ValueError('override_saved_profile must be boolean and needs an explicit profile')
    argv = []
    if variant != 'default': argv.append('--uncensored' if variant == 'uncensored' else '--official')
    # Variant chooses weights within the hardware-selected family, not FLUX.
    if 'profile' in args: argv += ['--profile', profile]
    if override: argv.append('--override-saved-profile')
    for key in ('negative', 'width', 'height', 'seed', 'steps'):
        if key not in args or args[key] is None: continue
        value = args[key]
        if key == 'negative':
            if not isinstance(value, str) or len(value) > 16000 or '\x00' in value:
                raise ValueError('Invalid negative prompt')
        elif type(value) is not int:
            raise ValueError(key + ' must be an integer')
        argv += ['--' + key + '=' + str(value)]
    return [*argv, '--', prompt]


def media_argv(root, boot, command, arguments):
    if command not in MEDIA_COMMANDS:
        raise PermissionError('Unknown registered media command; call available_tools for supported commands')
    if not isinstance(arguments, list) or len(arguments) > 128 or any(
            not isinstance(a, str) or '\x00' in a or len(a) > 32000 for a in arguments):
        raise ValueError('arguments must be a bounded array of literal strings')
    return [str(boot), str(root/'Agent/ai_tools.py'), command, *arguments]


TOOLS = [
    {'type': 'function', 'function': {
        'name': 'generate_image',
        'description': 'Generate local images using the CURRENT saved Images profile. Omit profile normally; a named saved profile stays pinned, including repeat requests. Never choose SD1.5 merely to obtain uncensored weights. Variant follows Media models independently of chat; auto permits standard/uncensored for the request. available_tools lists pairs. klein4 has CPU/Vulkan encoders (128..512px, 12/16 GiB free RAM); flux needs CUDA. Use returned preview URLs.',
        'parameters': {'type': 'object', 'properties': {
            'prompt': {'type': 'string'}, 'negative': {'type': 'string'},
            'profile': {'type': 'string', 'enum': ['auto', 'sd15', 'klein4', 'flux'],
                        'description': 'Omit to use Settings. A named saved Images choice wins unless override_saved_profile is true. With saved Automatic, this can select a family.'},
            'override_saved_profile': {'type':'boolean', 'description':'Default false. Set true with profile ONLY when the current user explicitly requests a different image model for this job, not for a repeated prompt, hardware guess or variant choice.'},
            'variant': {'type': 'string', 'enum': ['default', 'standard', 'uncensored'],
                        'description': 'default follows the saved media setting. In media auto, choose standard or uncensored within the selected family. DreamShaper 8 is the SD1.5 alternate; this is not permission to change a saved FLUX profile.'}
        }, 'required': ['prompt'], 'additionalProperties': False}}},
    {'type': 'function', 'function': {
        'name': 'media_tool',
        'description': 'Run local media using command and literal CLI strings. Use known syntax directly; ["--help"] is for a specific unknown option. Omit engine/profile to follow CURRENT Settings. Do not copy an earlier job\'s overrides into a repeat request. Media auto permits per-request --official/--uncensored choices; fixed media preferences use omitted flags unless the user overrides. video-small is silent text-to-video (Wan1.3B CPU/Vulkan); video preserves an input image (Wan2.2 Windows CUDA or VACE1.3B Radeon/Linux GPU); music/score-video auto fits ACE-Step GPU or MusicGen CPU after chat unload. CPU --engine musicgen-cpu requires --instrumental, no lyrics, 1..30s, 10 GiB free RAM; noncommercial CC-BY-NC-4.0 weights, no separate prompt filter. Never drop vocals or truncate duration. Image calls pin named saved profiles; --override-saved-profile with --profile is only for a user-requested one-off model change. Other explicit engine/profile flags override defaults within supported routes. edit --edit-profile klein4 uses CPU/Vulkan; semantic targets need GPU segmentation. Voice/music/MMAudio/VACE: no separate runtime filter found. dialogue-video arguments=[IMAGE,WORDS,"--duration","20","--motion",ACTION] makes a 20-second video. Optional --dialogue-start defaults to 0; runtime measures natural speech and checks it fits. No prerequisite catalog/history lookup or speech/frame calculation.',
        'parameters': {'type': 'object', 'properties': {
            'command': {'type': 'string'},
            'arguments': {'type': 'array', 'items': {'type': 'string'}}
        }, 'required': ['command'], 'additionalProperties': False}}},
    {'type': 'function', 'function': {
        'name': 'available_tools',
        'description': 'List registered local media capabilities, independent saved chat/media variant preferences, engine/profile defaults and standard/uncensored model pairs. Supply command for its compact usage; detail=full is optional model/reference metadata, not a prerequisite. Known syntax needs no lookup. This is discovery, not an inference or hardware test.',
        'parameters': {'type': 'object', 'properties': {'command': {'type': 'string', 'description':'Optional tool/command, e.g. generate_image, image, video, voice-say or science.'}, 'detail': {'type':'string','enum':['summary','full'],'description':'Default summary. Full is only for a specific metadata question.'}},
                       'additionalProperties': False}}}
]
