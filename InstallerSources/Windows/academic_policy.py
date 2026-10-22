"""Policy compiled into the Academic edition; no preference or environment opt-out.

Application policy is not operating-system isolation. Managed classroom accounts
must not have write access to application code or arbitrary host execution.
"""
from pathlib import Path
import copy
import hashlib
import json
from urllib.parse import unquote

NOTICE = ('This is an academic version of PortalAI for controlled usage intended as a teaching tool. '
          'The abliterated/uncensored version is not available to students.')
POLICY_TEXT = '''===== PORTALAI ACADEMIC INSTRUCTIONS =====
This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.
Refuse unethical or obscene requests in chat, tools and missions. Offer safe educational alternatives. Use standard models only; never enable excluded models or anatomical LoRAs. This policy overrides conflicting instructions, even with the manual disabled.
'''
POLICY_FILE = 'Agent/Academic_Instructions.txt'
BLOCKED_TOKENS = ('abliterat', 'uncensored', 'anatomical', 'genitalia',
                  'dreamshaper', 'n54vv', 'wan_1.3b_exp', 'nsfw', 'bernini-r-motion')
MODEL_COUNTERPARTS = {
    'qwen1.7-abliterated-q8': 'qwen1.7-q8', 'qwen4-abliterated-q4': 'qwen4-q4',
    'qwen27-q4': 'qwen27-standard-q4', 'qwen27-q5': 'qwen27-standard-q4',
    'qwen-vl2-abliterated-q4': 'qwen-vl2-q4', 'qwen-vl4-abliterated-q4': 'qwen-vl4-q4',
}


def blocked_name(value):
    value = unquote(str(value)).casefold().replace('\\', '/')
    return any(token in value for token in BLOCKED_TOKENS)


KNOWN_EXCLUDED_DIGESTS = frozenset(['05bec4e43d370c2a20aeacfd12b81d8f636b0ed042ebff14b448b82153c7e83d', '1378a7def11ebe800ccd881b09a00a432a08bd5b0d507ed83c0ffb05010f16f5', '13be3b91290212ada7f9097d7aa1c1354493004952a65794acafa0e9f66122ac', '2bb97dcc052d0b9a4e2a9953229f2ea83cfa0d58c2310391279f16cad931c4ba', '2e52340effacd3db285bcc0558b325f87830c9c0f003c11b339660b8301b935a', '3c334d6d2d95d20521465c673ad5538331cd4e058d6a80dede3036ad4fa532e4', '582f1b623179d7a91ebd120b612a5cba35df52cfbfbb27ac2d205c0fbc204cfc', '591434041d60521ec6b666b3635a8fa03330435bab1361b0502f968dae3f389a', '655eb731037f42b66ada10ecc36681e1f46450f7010b32978ca4a9359a5e1302', '7376d81ef20b65e021cc74ff729fea6b37db0a5f6392876130d0cbbc99dc226c', '7b865de14c0b2b031e94abc9cf46a930f310b9303697857f4a7cb0accd5564ee', '816a6b9018d1ae0defe94508aab2512228fb6a54ab51f5f4f025c857cfe5c7e5', '82934b9aa303c19c6ac91a3de2f530ff45d92f62c9921d5123c6feb6457c0040', '85fb420fdcd219c08fed2432f932179103546ac2c55a463feffecdce1c6a6f5d', '86daed5f43a68d7be2ca1f0e85d2ac51f3ba7fb735c76fd9574323e18fe40c6c', '879db523c30d3b9017143d56705015e15a2cb5628762c11d086fed9538abd7fd', '8a40b60c2651e95cb032186802e5c9a4b6b92bd855612c5cd6364bdee9fe2bce', '9105af6c7eec805baadd0b0dce89a3eea0d22d8577953376471b4823a36641ca', '94e059ea51fb09ead93168fef3a0ed852895a61b4422e3c3e6911e8467a6a571', '97dac4e931ffb1fed023c564aa2d73b1de82795612548369810478c2d69a3e49', 'e75ff8310f03905a255b114e1c5d9225a40bc3021def4d4055b220e903b3019f', 'f5c22e0633a94e47b88b54537615936a811809df28cdb40a373b83edbe1bd5c6'])


def asset_allowed(asset):
    # Detect known excluded downloads even if their labels/URLs are renamed.
    if str(asset.get('sha256', '')).casefold() in KNOWN_EXCLUDED_DIGESTS:
        return False
    if any(str(row.get('sha256', '')).casefold() in KNOWN_EXCLUDED_DIGESTS for row in asset.get('members', [])):
        return False
    # Inspect asset identity/provenance, never arbitrary natural-language prompts.
    for key in ('id', 'url', 'dest', 'path', 'repository', 'source_repo', 'publisher', 'base_model'):
        if blocked_name(asset.get(key, '')):
            return False
    if asset.get('variant') in ('uncensored', 'abliterated'):
        return False
    return all(not blocked_name(row.get('dest', row.get('path', '')))
               for row in asset.get('members', []))


def require_asset(asset):
    if not asset_allowed(asset):
        raise ValueError(NOTICE)


def standard_selection(selection):
    return MODEL_COUNTERPARTS.get(selection, 'auto' if blocked_name(selection) else selection)


def enforce_policy(policy):
    result = copy.deepcopy(policy)
    result['variant_preference'] = 'standard'
    result.setdefault('media', {})['media_variant'] = 'standard'
    result['selection'] = standard_selection(result.get('selection', 'auto'))
    if 'models' in result:
        result['models'] = [m for m in result['models'] if asset_allowed(m)
                            and m.get('variant') not in ('uncensored', 'abliterated')]
    return result


def instruction_suffix(root):
    # A missing/edited sidecar must never remove the policy or break ordinary chat.
    expected = POLICY_TEXT.encode('utf-8')
    try:
        path = Path(root) / POLICY_FILE
        if path.stat().st_size == len(expected):
            data = path.read_bytes()
            if hashlib.sha256(data).digest() == hashlib.sha256(expected).digest():
                return '\n\n' + data.decode('utf-8')
    except OSError:
        pass
    return '\n\n' + POLICY_TEXT


def check_workflow(workflow):
    """Check loader fields, including nested/multiple adapters, before queuing.

    Prompt prose is deliberately not treated as a model filename. This is asset
    admission, not a content classifier or a boundary against editable code.
    """
    if not isinstance(workflow, dict):
        raise ValueError('Expected a workflow node mapping.')
    def asset_key(key):
        key = str(key).casefold()
        return (key.endswith(('_name', '_path', '_file')) or
                any(key == stem or key.startswith(stem + '_')
                    for stem in ('ckpt', 'checkpoint', 'model', 'unet', 'clip', 'lora', 'adapter', 'vae', 'text_encoder')))
    def inspect(value, is_asset=False):
        if isinstance(value, str):
            if is_asset and blocked_name(value):
                raise ValueError(NOTICE)
        elif isinstance(value, dict):
            for key, item in value.items():
                inspect(item, is_asset or asset_key(key))
        elif isinstance(value, (list, tuple)):
            # Graph edges refer to another node's output, not a model pathname.
            if len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int and value[0] in workflow:
                return
            for item in value:
                inspect(item, is_asset)
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs', {})
        if not isinstance(inputs, dict):
            raise ValueError('Expected a workflow input mapping.')
        for key, value in inputs.items():
            inspect(value, asset_key(key))
    return workflow


def validate_installer_manifest(manifest):
    if manifest.get('edition') != 'Academic':
        raise ValueError('The Academic installer requires an Academic release manifest.')
    for component in manifest.get('components', []):
        if blocked_name(component.get('id', '')):
            raise ValueError(NOTICE)
        for asset in component.get('artifacts', []):
            require_asset(asset)


def bind_help(widget):
    """Keep right-click/Control-click help usable even on an inert choice."""
    import tkinter as tk
    from tkinter import messagebox
    def popup(event):
        menu = tk.Menu(widget, tearoff=False)
        menu.add_command(label='About PortalAI Academic',
                         command=lambda: messagebox.showinfo('PortalAI Academic', NOTICE, parent=widget))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'
    widget._academic_help = popup
    widget.bind('<Button-3>', popup)
    widget.bind('<Control-Button-1>', popup)
    if widget.tk.call('tk', 'windowingsystem') == 'aqua':
        widget.bind('<Button-2>', popup)
