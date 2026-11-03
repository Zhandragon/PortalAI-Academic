"""Small, advisory image checks: source association is not face recognition."""
import io
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit


def candidate_quality(url, page_url='', hint=''):
    try:image=urlsplit(url); page=urlsplit(page_url)
    except ValueError:return {'image_role':'candidate','likely_placeholder':False,'exact_match_verified':False}
    path=image.path.lower(); hint=str(hint).lower()
    role='candidate'; reason='Image link only; pictured subject has not been verified.'
    placeholder=bool(re.search(r'(?:avatar_scholar_\d+|default[-_]?(?:avatar|profile)|identicon|avatar[-_]default)',path))
    if placeholder:
        role='placeholder';reason='URL identifies a default or generated avatar; do not present it as a person photo.'
    elif re.search(r'(?:cleardot|spacer|tracking[-_]pixel)\.(?:gif|png)$',path):
        role='decorative';reason='Likely tracking or layout image.'
    elif (page.hostname in ('scholar.google.com','scholar.google.co.uk') and
          image.hostname in ('scholar.google.com','scholar.googleusercontent.com')):
        user=parse_qs(page.query).get('user');photo_user=parse_qs(image.query).get('user')
        if user and photo_user:
            role='profile_image' if user==photo_user else 'related_profile_image'
            reason=('Image URL belongs to the same Scholar profile ID.' if user==photo_user else
                    'Image URL belongs to another profile on this page; do not substitute it for the main subject.')
    if role=='candidate' and ('json_ld:person' in hint or re.search(r'profile[-_ ]?(?:photo|image|picture)|gsc_prf_pup-img',hint)):
        role='profile_image';reason='Page markup labels this as a profile/person image; verify the page identity.'
    if role=='candidate' and re.search(r'\b(?:logo|icon|banner)\b',hint):role='decorative'
    return {'image_role':role,'likely_placeholder':placeholder,'association_evidence':reason,'exact_match_verified':False}


def assess_image(raw, url, root):
    """Check known avatar URLs, then tiny GitHub raster geometry if Pillow exists.

    No face detection or identity inference. Unavailable/ambiguous analysis stays
    unknown. Only the portable, already-installed Pillow layer is considered.
    """
    result=candidate_quality(url)
    result['visual_check']='not_performed'
    if result['likely_placeholder'] or urlsplit(url).hostname!='avatars.githubusercontent.com':return result
    layers=[Path(root)/p for p in ('Runtime/SciencePackages','Runtime/ScientificPython/packages','Runtime/LinuxPackages/science')]
    layer=next((p for p in layers if (p/'PIL/__init__.py').is_file()),None)
    if layer is None:
        result['visual_check']='unavailable';return result
    try:
        sys.path.insert(0,str(layer))
        try:from PIL import Image
        finally:sys.path.remove(str(layer))
        with Image.open(io.BytesIO(raw)) as source:
            result['dimensions']=list(source.size)
            if source.width*source.height>1_048_576 or min(source.size)<16:return result
            if source.width!=source.height:return result
            source.seek(0)
            small=source.convert('RGB').resize((32,32),Image.Resampling.NEAREST)
            pixels=list(small.getdata());colors=set(pixels)
            mirror_error=sum(abs(pixels[y*32+x][c]-pixels[y*32+31-x][c]) for y in range(32) for x in range(32) for c in range(3))/(32*32*3)
            result['visual_check']='bounded_avatar_geometry'
            if 2<=len(colors)<=8 and mirror_error<1.5:
                result.update(image_role='likely_placeholder',likely_placeholder=True,
                    association_evidence='GitHub avatar has a few-color symmetric geometric pattern, consistent with an identicon. Not a verified person photo.')
    except Exception:result['visual_check']='unavailable'
    return result
