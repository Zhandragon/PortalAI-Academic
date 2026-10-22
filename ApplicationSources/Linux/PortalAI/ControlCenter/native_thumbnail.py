"""Bounded image thumbnail worker. Private pixels use pipes, never temporary files."""
import io
import sys
from pathlib import Path


def thumbnail(data):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ('JPEG', 'PNG', 'GIF', 'WEBP'):
            raise ValueError('unsupported_image')
        if min(image.size) < 1 or max(image.size) > 16384 or image.width*image.height > 20000000:
            raise ValueError('image_dimensions')
        image.seek(0)
        image.draft('RGB', (640,640))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((640,640))
        # New pixel-only image omits EXIF, location, comments and profiles.
        clean = Image.new('RGB', image.size, 'white')
        if image.mode in ('RGBA','LA') or 'transparency' in image.info:
            rgba=image.convert('RGBA');clean.paste(rgba, mask=rgba.getchannel('A'))
        else:
            clean.paste(image.convert('RGB'))
        for edge, quality in ((640,75),(512,65),(384,55),(256,45)):
            clean.thumbnail((edge,edge))
            result=io.BytesIO();clean.save(result,format='JPEG',quality=quality)
            if result.tell() <= 24576:
                return result.getvalue()
    raise ValueError('thumbnail_limit')


if __name__ == '__main__':
    root=Path(__file__).resolve().parents[1]
    # Use the shipped Pillow layer, isolated from account and global packages.
    layers=[root/'Runtime/SciencePackages',root/'Runtime/ScientificPython/packages',root/'Runtime/LinuxPackages/science']
    layer=next((p for p in layers if (p/'PIL/__init__.py').is_file()),None)
    if layer is None:raise SystemExit(2)
    sys.path.insert(0,str(layer))
    try:
        data=sys.stdin.buffer.read(20*1024*1024+1)
        if len(data)>20*1024*1024:raise ValueError('input_limit')
        sys.stdout.buffer.write(thumbnail(data))
    except Exception:
        raise SystemExit(2)
