import hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Tools'),str(ROOT/'Runtime/SciencePackages')]
from native_thumbnail import thumbnail
from PIL import Image
from vision_diagnostics import rows
import runtime_policy

class VisionTests(unittest.TestCase):
    def test_large_synthetic_photo_becomes_single_chunk_without_exif(self):
        im=Image.effect_noise((2000,1500),70).convert('RGB');exif=Image.Exif();exif[270]='synthetic-private-metadata'
        raw=io.BytesIO();im.save(raw,'JPEG',quality=95,exif=exif)
        data=thumbnail(raw.getvalue());self.assertLessEqual(len(data),24576)
        with Image.open(io.BytesIO(data)) as result:
            self.assertLessEqual(max(result.size),640);self.assertEqual(dict(result.getexif()),{})
        self.assertGreater(len(raw.getvalue()),len(data)*10)
    def test_invalid_image_is_refused(self):
        with self.assertRaises(Exception):thumbnail(b'<html>not an image</html>')
    def test_all_pairs_routing_and_checksum_corruption(self):
        policy=runtime_policy.load_policy(ROOT)
        pins=json.loads((ROOT/'Agent/small_vision_assets.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Agent').mkdir()
            for index,pin in enumerate(pins):
                data=f'public synthetic asset {index}'.encode();path=root/pin['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                pin.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            (root/'Agent/small_vision_assets.json').write_text(json.dumps(pins))
            with patch.object(runtime_policy,'load_policy',return_value=policy):
                result=rows(root,verify=True);self.assertEqual(len(result),12);self.assertTrue(all(r['status']=='PASS' for r in result),result)
                path=root/pins[0]['path'];data=path.read_bytes();path.write_bytes(b'X'+data[1:])
                self.assertTrue(any(r['status']=='FAIL' and 'SHA-256' in r['detail'] for r in rows(root,verify=True)))
