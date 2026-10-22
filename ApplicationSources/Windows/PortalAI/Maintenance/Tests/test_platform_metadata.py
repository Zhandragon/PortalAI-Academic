"""Installed metadata must use the selected OS and not equate files with GPU validation."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
import bundle_inventory as inventory
from workload_compatibility import support_matrix


class PlatformMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def touch(self,*paths):
        for relative in paths:
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.touch()

    def rows(self,system):
        with patch.object(inventory.platform,'system',return_value=system),\
             patch.object(inventory,'inventory',return_value={'models':[],'backends':{}}):
            return inventory.installed_rows(self.root)

    def test_denied_backend_does_not_abort_inventory_or_claim_missing(self):
        from unittest.mock import Mock
        denied=Mock();denied.stat.side_effect=PermissionError('restricted backend')
        with patch.object(inventory,'runtime_candidates',return_value={'vulkan':denied}), \
             patch.object(inventory,'load_policy',return_value={'models':[]}), \
             patch.object(inventory,'storage_budget',return_value={}):
            result=inventory.inventory(self.root)
            self.assertFalse(result['backends']['vulkan'])
            self.assertEqual(result['backend_states']['vulkan'],'INACCESSIBLE')
            self.assertEqual(inventory.installed_rows(self.root)['backend_vulkan'][0],'INACCESSIBLE')

    def test_denied_optional_component_does_not_abort_package_page(self):
        original=Path.exists
        def exists(path):
            if 'AMDPython' in path.parts:raise PermissionError('restricted package')
            return original(path)
        with patch.object(Path,'exists',exists):
            self.assertEqual(self.rows('Windows')['amdTorch'][0],'CHECK')

    def test_windows_files_do_not_mark_linux_engines_installed(self):
        self.touch('Runtime/BootstrapPython/python.exe','Runtime/StableDiffusion/windows-vulkan/sd-cli.exe',
                   'Runtime/StableDiffusion/windows-cpu/sd-cli.exe','Runtime/AMDPython/packages/torch/__init__.py',
                   'Tools/ffmpeg/bin/ffmpeg.exe','Tools/ffmpeg/bin/ffprobe.exe','Agent/media_edit_bridge.py')
        rows=self.rows('Linux')
        for key in ('imageVulkan','imageNativeCpu','amdTorch','mediaEdit'):self.assertEqual(rows[key][0],'CHECK')
        rows=self.rows('Windows')
        for key in ('imageVulkan','imageNativeCpu','amdTorch','mediaEdit'):self.assertEqual(rows[key][0],'INSTALLED')

    def test_vm_bridge_alone_does_not_mean_payload_installed(self):
        self.touch('Agent/vm_runner.py','Runtime/LinuxPython/run-python')
        self.assertEqual(self.rows('Linux')['vmMode'][0],'CHECK')
        self.touch('Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
                   'Runtime/QEMU/linux-x64/bin/qemu-system-x86_64','Runtime/VM/alpine-3.24.2/boot/vmlinuz-virt',
                   'Runtime/VM/alpine-3.24.2/boot/initramfs-virt')
        status,detail=self.rows('Linux')['vmMode']
        self.assertEqual(status,'INSTALLED');self.assertIn('/dev/kvm',detail);self.assertIn('pending',detail)

    def test_piper_requires_os_package_and_complete_voice_assets(self):
        self.touch('Runtime/BootstrapPython/python.exe','Voice/Piper/packages/piper/__init__.py',
                   'Voice/Piper/models/en_US-ljspeech-medium.onnx','Voice/Piper/models/en_US-ljspeech-medium.onnx.json')
        self.assertEqual(self.rows('Windows')['piperCpu'][0],'CHECK')
        self.touch('Voice/Piper/models/MODEL_CARD')
        self.assertEqual(self.rows('Windows')['piperCpu'][0],'INSTALLED')
        self.assertEqual(self.rows('Linux')['piperCpu'][0],'CHECK')

    def test_linux_sd_wrapper_requires_binary_and_loader(self):
        self.touch('Runtime/StableDiffusion/linux-cpu/sd-cli')
        self.assertEqual(self.rows('Linux')['imageNativeCpu'][0],'CHECK')
        self.touch('Runtime/StableDiffusion/linux-cpu/sd-cli.bin',
                   'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2')
        self.assertEqual(self.rows('Linux')['imageNativeCpu'][0],'INSTALLED')

    def test_linux_science_does_not_use_windows_site_packages(self):
        self.touch('Runtime/LinuxPython/run-python',
                   'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
                   'Scientific/science_core.py','Agent/scientific_tool_bridge.py',
                   'Scientific/python/Lib/site-packages/openmm/__init__.py')
        self.assertEqual(self.rows('Linux')['scienceProtein'][0],'CHECK')
        self.touch('Runtime/LinuxPackages/science/openmm/__init__.py')
        self.assertEqual(self.rows('Linux')['scienceProtein'][0],'INSTALLED')

    def test_support_matrix_distinguishes_provisioning_and_validation(self):
        rows=support_matrix();text=' '.join(row['linux'] for row in rows)
        self.assertNotIn('Not provisioned',text)
        self.assertIn('/dev/kvm',text);self.assertIn('unvalidated',text)
        sfx=next(row for row in rows if 'Text/video-conditioned' in row['workload'])
        self.assertIn('BF16',sfx['windows_radeon_igpu'])
        self.assertIn('physical Radeon inference pending',sfx['windows_radeon_igpu'])

    def test_linux_music_command_without_models_or_receipts_is_partial(self):
        self.touch('Runtime/LinuxPython/run-python',
                   'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
                   'Agent/music_understanding_enhanced.py')
        status,detail=self.rows('Linux')['musicUnderstand']
        self.assertEqual(status,'PARTIAL');self.assertIn('CLAP missing/incomplete',detail)

    def music_payload(self):
        from music_understanding_runtime import VERSIONS,DEMUCS_MODEL
        self.touch('Runtime/LinuxPython/run-python',
                   'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
                   'Agent/music_understanding_enhanced.py','Agent/music_understanding_runtime.py',
                   'MusicUnderstanding/runtime_driver.py','Runtime/LinuxTorch/cpu/torch/__init__.py',
                   'Runtime/LinuxTorch/cpu/torchaudio/__init__.py',
                   'Runtime/LinuxPackages/media/transformers/__init__.py','Runtime/LinuxPackages/media/soundfile.py',
                   'Runtime/LinuxPackages/musicunderstanding/demucs/__init__.py',
                   'Runtime/LinuxPackages/musicunderstanding/julius/__init__.py',
                   'Runtime/LinuxPackages/musicunderstanding/sphn/__init__.py',
                   'MusicUnderstanding/models/CLAP-larger-music/config.json',
                   'MusicUnderstanding/models/CLAP-larger-music/pytorch_model.bin',DEMUCS_MODEL,
                   'MusicUnderstanding/models/MOSS-Music-8B-Instruct/config.json',
                   'MusicUnderstanding/models/MOSS-Music-8B-Instruct/shard.safetensors')
        folder=self.root/'Maintenance/Imports';folder.mkdir(parents=True)
        (folder/'linux-torch-cpu.json').write_text('{"verified":true}')
        (folder/'linux-musicunderstanding-lock.json').write_text(json.dumps({'verified':True,
            'assets':[{'name':name,'version':version} for name,version in VERSIONS.items()]}))
        (self.root/'MusicUnderstanding/models/MOSS-Music-8B-Instruct/model.safetensors.index.json').write_text(
            '{"weight_map":{"weight":"shard.safetensors"}}')

    def test_linux_music_payload_is_installed_without_claiming_full_moss_validation(self):
        self.music_payload()
        status,detail=self.rows('Linux')['musicUnderstand']
        self.assertEqual(status,'INSTALLED');self.assertIn('CLAP packaged',detail)
        self.assertIn('full MOSS and physical GPU inference unvalidated',detail)
        (self.root/'MusicUnderstanding/models/MOSS-Music-8B-Instruct/shard.safetensors').unlink()
        status,detail=self.rows('Linux')['musicUnderstand']
        self.assertEqual(status,'PARTIAL');self.assertIn('CLAP packaged',detail)
        self.assertIn('MOSS missing/incomplete',detail)

    def test_linux_music_corrupt_receipt_cannot_claim_installed(self):
        self.music_payload()
        for content in ('{broken','[]','{"verified":true,"assets":[null]}'):
            (self.root/'Maintenance/Imports/linux-musicunderstanding-lock.json').write_text(content)
            self.assertEqual(self.rows('Linux')['musicUnderstand'][0],'PARTIAL')

    def test_linux_electrical_does_not_infer_kicad_from_wrapper_alone(self):
        self.touch('Runtime/LinuxPython/run-python','Runtime/KiCad/linux-x64/bin/kicad-cli',
                   'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
                   'Scientific/science_core.py','Agent/scientific_tool_bridge.py','Runtime/LinuxPackages/science/numpy')
        status,detail=self.rows('Linux')['scienceElectrical']
        self.assertEqual(status,'INSTALLED');self.assertIn('KiCad export payload missing/incomplete',detail)
        self.touch('Runtime/LinuxSystem/kicad/usr/bin/kicad-cli',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/ld-linux-x86-64.so.2',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/_eeschema.kiface',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/_pcbnew.kiface',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/symbols/Device.kicad_sym',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/footprints/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/3dmodels/Resistor_SMD.3dshapes/R_0805_2012Metric.step')
        receipts=self.root/'Maintenance/Imports';receipts.mkdir(parents=True)
        for filename in ('linux-system-kicad.json','linux-system-kicad-resources.json'):
            (receipts/filename).write_text('{"verified":true}')
        self.assertIn('SVG/BOM/STEP exports checked',self.rows('Linux')['scienceElectrical'][1])
        (receipts/'linux-system-kicad-resources.json').write_text('{"verified":false}')
        self.assertIn('KiCad export payload missing/incomplete',self.rows('Linux')['scienceElectrical'][1])

    def test_missing_linux_cuda_llm_distinguished_from_media_layer(self):
        with patch.object(inventory.platform,'system',return_value='Linux'),\
             patch.object(inventory,'inventory',return_value={'models':[],'backends':{'cuda':False}}):
            status,detail=inventory.installed_rows(self.root)['backend_cuda']
        self.assertEqual(status,'NOT INSTALLED');self.assertIn('Vulkan',detail)
        self.assertIn('media layer is separate',detail)


if __name__=='__main__':unittest.main()
