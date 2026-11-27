"""Optional model downloads; never invoked automatically by image generation."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
ID='qwen-image-edit-2511-lightning'

def catalog(root=ROOT):
    manifest=json.loads((Path(root)/'Agent/qwen_image_edit_assets.json').read_text('utf-8'))
    if manifest.get('optional') is not True or manifest.get('included_by_default') is not False:
        raise ValueError('Qwen image weights must remain an optional download')
    return manifest

def install(root=ROOT, *, accepted=False):
    if accepted is not True:raise ValueError('Review and accept the Qwen and Lightning model terms before downloading')
    from import_foundation_assets import install as install_asset
    from runtime_policy import require_space,atomic_json
    root=Path(root);manifest=catalog(root)
    require_space(root,sum(a['size'] for a in manifest['assets'] if not (root/a['dest']).exists()))
    results=[install_asset(a,root) for a in manifest['assets']]
    atomic_json(root/'Maintenance/Imports/qwen-image-edit-consent.json',
        {'schema':1,'accepted':True,'manifest':manifest,'results':results})
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--accept-model-terms',action='store_true',help='Confirm you reviewed the linked publisher/model terms')
    args=parser.parse_args()
    print(json.dumps(install(accepted=args.accept_model_terms) if args.install else catalog(),indent=2))

if __name__=='__main__':main()
