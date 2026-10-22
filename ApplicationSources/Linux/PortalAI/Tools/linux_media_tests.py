"""Real Linux media/science tests in the offline, bounded validation guest."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path('/portable');sys.path.insert(0,str(ROOT/'Agent'))
from platform_runtime import python_path,ffmpeg_path
from process_diagnostics import excerpt

CASES={
 'native-flux-contracts':"""
import unittest
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
from linux_ml import activate
activate(backend='cpu')
suite=unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern='test_native_flux.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun>=6
print('Linux native Klein4 contract tests with synthetic weights, real FFmpeg masked composition; no model/GPU inference claim.',flush=True)
""",
 'biology':"""
import unittest
sys.path[:0]=[str(ROOT),str(ROOT/'Tools'),str(ROOT/'Runtime/LinuxPackages/science'),str(ROOT/'Validation/Tests')]
suite=unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern='test_biology.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and not result.skipped and result.testsRun>=23
cp=subprocess.run([str(python_path(ROOT)),'-B',str(ROOT/'Tools/smoke_biology.py'),'--wrapper','--artifacts-dir',str(ROOT/'Maintenance/Validation/BiologySmoke')],capture_output=True,text=True,timeout=150)
print(cp.stdout,flush=True)
assert cp.returncode==0,cp.stderr+'\\n'+cp.stdout
print('Actual offline Linux biology invariants and bounded CPU ProteinMPNN weight inference passed; no physical GPU claim.',flush=True)
""",
 'remaining-media':"""
import unittest
from linux_ml import activate
activate(backend='cpu')
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
suite=unittest.TestSuite()
for pattern in ('test_audio_inpaint_scaled.py','test_dialogue_portable.py','test_remaining_media_routes.py'):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun>=30,{'tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors)}
print(json.dumps({'tests':result.testsRun,'skipped':len(result.skipped),'scope':'Actual offline Linux imports, masked flow/PCM math, CLI routing, staged orchestration, Stop and publication checks; synthetic models only, not physical GPU inference'}),flush=True)
""",
 'incremental-profiles':"""
import unittest
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
suite=unittest.TestSuite()
for pattern in ('test_profile_incremental.py','test_profile_hydration*.py','test_profile_workspace.py','test_profile_snapshot_stream.py'):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun>=60,{'tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors)}
print(json.dumps({'tests':result.testsRun,'skipped':len(result.skipped),'scope':'Real Linux incremental encryption, lazy restore, atomic publication, interrupted child recovery, loopback child tools and consumer integration; synthetic profiles only'}),flush=True)
""",
 'web-tls':"""
import hashlib,ssl,unittest
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
from web_tls import default_context,portable_context,BUNDLE_RELATIVE,BUNDLE_BYTES,BUNDLE_SHA256
receipt=json.loads((ROOT/'Maintenance/Imports/web-ca-bundle.json').read_text())
assert receipt['verified'] is True and receipt['ca_certificates']==121,receipt
for row in receipt['files']:
    data=(ROOT/row['path']).read_bytes()
    assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
bundle=next(row for row in receipt['files'] if row['path']==BUNDLE_RELATIVE)
assert bundle['bytes']==BUNDLE_BYTES and bundle['sha256']==BUNDLE_SHA256
for factory in (default_context,portable_context):
    context=factory()
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    assert context.cert_store_stats()['x509_ca']>=121,context.cert_store_stats()
suite=unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern='test_web_tls.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and not result.skipped and result.testsRun>=8,{'tests':result.testsRun,'skipped':len(result.skipped)}
print('Actual Linux: portable CA receipt and bytes verified; system-plus-portable and diagnostic-only contexts require certificate/hostname verification; '+str(result.testsRun)+' offline TLS tests passed',flush=True)
""",
 'local-accounts':"""
import unittest
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
suite=unittest.TestSuite()
for pattern in ('test_local_accounts.py','test_comfy_entry_order.py'):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful() and not result.skipped and result.testsRun>=49,{'tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors)}
print(str(result.testsRun)+' synthetic account cryptography and Comfy startup-order tests passed',flush=True)
""",
 'account-surface':"""
import runpy
runpy.run_path(str(ROOT/'Tools/linux_account_surface_tests.py'),run_name='__main__')
""",
 'launcher':"""
import runpy
runpy.run_path(str(ROOT/'Tools/linux_launcher_tests.py'),run_name='__main__')
""",
 'kicad':"""
import runpy
runpy.run_path(str(ROOT/'Tools/linux_kicad_tests.py'),run_name='__main__')
""",
 'music-specialists':"""
import gc,importlib.util,math,wave
from music_understanding_runtime import run,available,activate,plan
audio=ROOT/'Outputs/music-specialist-fixture.wav'
import array
samples=array.array('h',(int(4000*math.sin(i*2*math.pi*440/16000)) for i in range(8000)))
with wave.open(str(audio),'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(samples.tobytes())
for kind in ('clap','separate-vocals'):
    ready,reason=available(ROOT,kind);assert ready,reason
    arguments=[kind,'--audio',str(audio),'--device','cpu']
    if kind=='clap':arguments+=['--genre-labels','["synthetic tone", "music"]','--instrument-labels','["voice", "sine wave"]']
    response=run(ROOT,arguments,150)
    assert response.returncode==0,excerpt(response.stderr,4500)
    data=json.loads(next(line for line in reversed(response.stdout.splitlines()) if line.startswith('{')))
    if kind=='clap':
        assert data['backend']=='cpu' and len(data['genre'])==2 and data['instruments_voices'],data
    else:
        import wave
        assert Path(data['vocals_path']).is_file() and data['torch_backend']=='cpu',data
        # Float WAV is validated with SoundFile after CPU layer activation below.
    print(kind+': actual offline CPU inference through owned bounded worker passed',flush=True)
activate(ROOT,'cpu')
import torch,soundfile as sf,demucs,sphn
info=sf.info(data['vocals_path']);assert info.frames==22050 and info.channels==2 and info.samplerate==44100,info
sys.path.insert(0,str(ROOT/'MusicUnderstanding/MOSS-Music'))
from src.configuration_moss_music import MossMusicConfig
from src.modeling_moss_music import MossMusicModel
from src.processing_moss_music import MossMusicProcessor
config=MossMusicConfig(audio_config={'d_model':32,'output_dim':32,'encoder_layers':1,
    'encoder_attention_heads':4,'encoder_ffn_dim':64,'downsample_hidden_size':4,
    'max_source_positions':64,'n_window':16,'deepstack_encoder_layer_indexes':[0]},
    language_config={'vocab_size':64,'hidden_size':32,'intermediate_size':64,'num_hidden_layers':1,
    'num_attention_heads':4,'num_key_value_heads':2,'head_dim':8,'max_position_embeddings':128},
    adapter_hidden_size=64,deepstack_num_inject_layers=1)
model=MossMusicModel(config).eval()
with torch.inference_mode():
    result=model(input_ids=torch.tensor([[1,2,3,4]]),audio_data=torch.zeros((1,128,16)),
        audio_data_seqlens=torch.tensor([16]),audio_input_mask=torch.tensor([[False,True,True,False]]),use_cache=False)
assert tuple(result.logits.shape)==(1,4,64) and torch.isfinite(result.logits).all()
del model,result;gc.collect()
try:plan(ROOT,'moss','cpu')
except RuntimeError as error:assert '44 GiB' in str(error),str(error)
else:raise AssertionError('Full MOSS incorrectly admitted in 6 GiB guest')
print('MOSS tiny-config real audio/DeepStack/language forward passed; full 8B weights correctly rejected by guest RAM admission',flush=True)
""",
 'profiles':"""
import tempfile,unittest
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Validation/Tests')]
suite=unittest.TestSuite()
for pattern in ('test_local_accounts.py','test_profile_*.py','test_music_route_recovery.py'):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'Validation/Tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful(),{'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}
from profile_shutdown import verify_stopped,QuiescenceError
# The suite's parent is itself an owned bundled Python controller. It must not
# be ignored to manufacture a whole-installation quiescence success.
try:
    verification=verify_stopped(ROOT)
except QuiescenceError as error:
    assert 'ancestor' in str(error) or 'controller' in str(error),str(error)
else:
    assert verification['stopped'] is False,verification
with tempfile.TemporaryDirectory(prefix='profile-native-proc-') as folder:
    proof=verify_stopped(Path(folder))
    assert proof['stopped'] is True and not proof['remaining_owned_pids'],proof
import shutil,select
from unittest.mock import patch
import local_accounts,service_manager
from linux_job import LinuxJob
from profile_shutdown import stop_owned
with tempfile.TemporaryDirectory(prefix='profile-native-shutdown-') as folder:
    private=Path(folder)
    worker=job=foreign=None;store=None
    try:
        with patch.object(local_accounts,'_KDF_N',1024):
            store=local_accounts.LocalAccounts(private)
            account=store.bootstrap('GuestFixtureAdmin','synthetic guest shutdown passphrase')
            executable=private/'bin/busybox';executable.parent.mkdir();shutil.copy2('/usr/bin/busybox',executable)
            mission=private/'Data/Missions/fixture';mission.mkdir(parents=True)
            policy=mission/'run-policy.json';policy.write_text('{"enabled":true,"armed_at":123}')
            schedule=mission/'schedule.json';schedule.write_text('{"enabled":true,"epoch":"preserve"}')
            before=(policy.read_bytes(),schedule.read_bytes())
            marker={'user_id':account.user_id,'epoch':'c'*32,'state':'closing','controller_pid':os.getpid()}
            marker_path=private/'Private/active-session.json';marker_path.write_text(json.dumps(marker))
            worker=subprocess.Popen([str(executable),'sh','-c','read gate; setsid sleep 30 & echo $!; wait'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            job=LinuxJob(worker)
            worker.stdin.write(b'go\\n');worker.stdin.flush();worker.stdin.close()
            assert select.select([worker.stdout],[],[],5)[0],'synthetic child did not start'
            child=int(worker.stdout.readline())
            deadline=time.monotonic()+5
            while os.getsid(child)!=child and time.monotonic()<deadline:time.sleep(.01)
            assert os.getsid(child)==child,'child did not detach its session'
            assert job.group.name in Path('/proc',str(child),'cgroup').read_text()
            foreign=subprocess.Popen(['/usr/bin/busybox','sleep','30'])
            with patch.object(service_manager,'root_dir',return_value=private):
                receipt=stop_owned(private,account,marker)
            assert receipt['stopped'] is True and receipt['model_fenced'],receipt
            assert worker.wait(timeout=5)!=0 and not job.group.exists()
            state=Path('/proc',str(child),'stat')
            assert not state.exists() or state.read_text().rsplit(')',1)[1].split()[0]=='Z'
            assert foreign.poll() is None,'unrelated process was terminated'
            assert (policy.read_bytes(),schedule.read_bytes())==before
            assert json.loads(marker_path.read_text())==marker
            assert verify_stopped(private)['stopped'] is True
    finally:
        if job:job.close()
        for process in (worker,foreign):
            if process and process.poll() is None:process.kill()
            if process:process.wait(timeout=5)
        if store:store.logout()
print(json.dumps({'tests':result.testsRun,'skipped':len(result.skipped),
  'account_crypto':'real isolated Linux AES-GCM/Scrypt',
  'process_inventory':'real /proc identity, owned ancestor refusal and empty-root proof',
  'recovery_shutdown':'synthetic owned cgroup worker and detached child stopped; foreign process and armed policies preserved',
  'scope':'synthetic temporary profiles only; no host or production account state'}),flush=True)
""",
 'kornia-compat':"""
from linux_ml import activate
activate(backend='cpu')
import kornia_rs,kornia,torch,av
assert kornia_rs.__version__=='0.1.10'
assert '/kornia_compat/' in kornia_rs.__file__,kornia_rs.__file__
assert av.__version__=='16.1.0' and '/media/av/' in av.__file__,(av.__version__,av.__file__)
tensor=torch.full((1,3,8,8),.5)
filtered=kornia.filters.gaussian_blur2d(tensor,(3,3),(1.,1.))
assert filtered.shape==tensor.shape and torch.allclose(filtered,tensor,atol=1e-6)
from PIL import Image
path=ROOT/'Cache/kornia-compat.png';Image.new('RGB',(8,8),(1,2,3)).save(path)
pixels=kornia.io.load_image(path,kornia.io.ImageLoadType.RGB8)
assert tuple(pixels.shape)==(3,8,8)
kornia.io.write_image(ROOT/'Cache/kornia-compat-output.png',pixels)
assert Image.open(ROOT/'Cache/kornia-compat-output.png').size==(8,8)
activate(backend='cpu')
assert kornia_rs.__version__=='0.1.10'
print('Shared Linux Kornia compatibility import, Gaussian filter, PNG I/O and repeated activation passed; Whisper PyAV remains 16.1.0')
""",
 'gui-packaging':"""
result=subprocess.run([str(python_path(ROOT)),'-B','-I',str(ROOT/'Tools/linux_packaging_tests.py')],
    capture_output=True,text=True,timeout=100)
assert result.returncode==0,excerpt(result.stderr,4500)
line=next(s for s in result.stdout.splitlines() if s.startswith('PORTAL_PACKAGING_RESULT='))
report=json.loads(line.split('=',1)[1]);assert report['passed'],report
print(json.dumps(report),flush=True)
""",
 'llm-lifecycle':"""
import runpy
runpy.run_path(str(ROOT/'Tools/linux_llm_lifecycle.py'),run_name='__main__')
""",
 'genomics':"""
from scientific_tool_bridge import _activate
_activate()
from science_core import op_genome_msa,_find_kicad
result=op_genome_msa({'sequences':{'a':'ACGTACT','b':'ACGTCT','c':'ACGTACCT'},'threads':2},ROOT)
text=Path(result['file']).read_text()
assert text.count('>')==3,text
assert _find_kicad(ROOT)==str(ROOT/'Runtime/KiCad/linux-x64/bin/kicad-cli')
print('Bundled Linux MAFFT alignment passed; KiCad resolves its portable Linux wrapper')
""",
 'media-gui':"""
import os,sys,threading,wave
sys.path.insert(0,str(ROOT/'ControlCenter'))
import media_devices as devices
assert set(devices.capture_formats(str(ROOT)))=={'pulse','alsa'},devices.capture_formats(str(ROOT))
audio=ROOT/'Outputs/gui-audio.wav'
with wave.open(str(audio),'wb') as output:
    output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(bytes(8000))
environment=devices.desktop_env(ROOT);environment.update(SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='dummy')
played=subprocess.run(devices.owned_linux_command(ROOT,devices.linux_player_command(ROOT,audio,audio_only=True)),env=environment,capture_output=True,text=True,timeout=20)
assert played.returncode==0,played.stderr
original=devices.capture_command
devices.capture_command=lambda root,candidate:[str(ffmpeg_path(ROOT)),'-hide_banner','-loglevel','error','-nostdin','-re','-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-ac','1','-f','s16le','pipe:1']
stream=devices.LinuxPCMStream(ROOT,{'backend':'pulse','device_id':'default'})
stop=threading.Event();timer=threading.Timer(0.4,stop.set);timer.start()
try:stream.write_wav(ROOT/'Outputs/gui-capture.wav',stop)
finally:stream.close();timer.cancel();devices.capture_command=original
assert stream._process.poll() is not None
with wave.open(str(ROOT/'Outputs/gui-capture.wav'),'rb') as recorded:assert recorded.getnframes()>0 and recorded.getframerate()==16000
controller=\"import os,subprocess,sys,time;sys.path.insert(0,'/portable/ControlCenter');import media_devices as m;p=subprocess.Popen(m.owned_linux_command('/portable',[str(m.ffmpeg_path('/portable')),'-loglevel','error','-nostdin','-re','-f','lavfi','-i','anullsrc','-f','null','-']),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(p.pid,flush=True);time.sleep(0.3);os._exit(0)\"
result=subprocess.run([str(python_path(ROOT)),'-I','-c',controller],capture_output=True,text=True,timeout=10)
assert result.returncode==0,result.stderr
pid=int(result.stdout.strip());deadline=time.monotonic()+5
while time.monotonic()<deadline:
    state=Path('/proc')/str(pid)/'stat'
    if not state.exists() or state.read_text().split(') ',1)[1][0]=='Z':break
    time.sleep(0.05)
else:raise AssertionError('Media process survived its GUI parent')
print('Bundled FFplay null-device playback, Pulse/ALSA input support, synthetic PCM capture and GUI-death cleanup passed; physical devices unvalidated')
""",
 'supervision':"""
result=subprocess.run([str(python_path(ROOT)),'-B',str(ROOT/'Tools/linux_guest_tests.py')],capture_output=True,text=True,timeout=80)
print(result.stdout);print(result.stderr,file=sys.stderr)
assert result.returncode==0,result.stderr
line=next(s for s in result.stdout.splitlines() if s.startswith('PORTAL_LINUX_RESULT='))
assert json.loads(line.split('=',1)[1])['passed']
""",
 'media-tools':"""
import wave
path=ROOT/'Outputs/silence.wav'
with wave.open(str(path),'wb') as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(32000))
from media_edit_bridge import audio_edit,media_info
result=audio_edit(path,gain_db=-3)
assert media_info(result['files'][0])['has_audio']
from stt_bridge import SttBridge
result=SttBridge().transcribe(path,model='base',device='cpu',language='en',vad=False,beam_size=1)
assert result.get('success',True),result
print('Bundled FFmpeg audio processing and Whisper Base CPU inference passed')
""",
 'owned-tools':"""
import os,subprocess,sys,time
sys.path.insert(0,str(ROOT/'ControlCenter'))
from linux_owned_run import run
from runtime_policy import portable_env
from platform_runtime import python_path
result=run([str(python_path(ROOT)),'-c','print(6*7)'],cwd=ROOT,env=portable_env(ROOT),memory_bytes=512*1024**2)
assert result.returncode==0 and result.stdout.strip()=='42',result
from vm_runner import preflight,command_line
try:preflight(ROOT)
except RuntimeError as exc:assert '/dev/kvm' in str(exc),str(exc)
else:raise AssertionError('Nested KVM unexpectedly available; review before running nested VM')
args=command_line({'executable':'qemu','accelerator':'kvm','guest':'/guest','firmware':'/firmware','guest_memory_mib':512},ROOT/'init')
assert '-nic' in args and args[args.index('-nic')+1]=='none' and 'tcg' not in str(args)
print('Gated cgroup tool execution and no-KVM refusal passed; no host shell fallback')
from native_chat import ToolRuntime
runtime=ToolRuntime(ROOT,{'tool_timeout_seconds':40})
assert '42' in runtime.shell('python -c "print(6*7)"')
result=json.loads(runtime.science('run',{'code':'print(6*7)','timeout':20}))
assert result.get('success'),result
print('Native chat Linux shell and Science Workbench worker passed')
""",
 'comfy':"""
import urllib.request,json
from bounded_comfy import session
work=ROOT/'Cache/comfy-validation';work.mkdir(parents=True,exist_ok=True)
for name in ('user','input','output','temp'):(work/name).mkdir(exist_ok=True)
# Compare the original ABI package with the isolated compatibility override.
# Separate interpreters keep a native import failure out of the test controller.
probe="import sys;sys.path.insert(0,'/portable/Agent');from linux_ml import activate;activate(backend='cpu');"
if os.environ.get('PORTALAI_COMPARE_ORIGINAL_KORNIA')=='1':
    baseline=subprocess.run([str(python_path(ROOT)),'-B','-I','-X','faulthandler','-c',probe+
        "import kornia_rs;print(kornia_rs.__version__)"],capture_output=True,text=True,timeout=20)
    print('Original Kornia Rust import return code:',baseline.returncode,flush=True)
    if baseline.returncode:print(excerpt(baseline.stderr,1200),flush=True)
fixed=probe+"sys.path.insert(0,'/portable/Runtime/LinuxPackages/comfyextras');"+'''
import kornia_rs,kornia,torch
from pathlib import Path
assert kornia_rs.__version__=='0.1.10',kornia_rs.__version__
assert '/comfyextras/' in kornia_rs.__file__,kornia_rs.__file__
needed=['read_image_any','read_image_jpegturbo','read_image_png_u8','write_image_jpeg',
        'write_image_png_u8','write_image_tiff_u8','write_image_png_u16','write_image_tiff_u16','write_image_tiff_f32']
assert all(callable(getattr(kornia_rs,name,None)) for name in needed),[n for n in needed if not hasattr(kornia_rs,n)]
tensor=torch.full((1,3,8,8),.5)
assert kornia.filters.gaussian_blur2d(tensor,(3,3),(1.,1.)).shape==tensor.shape
from PIL import Image
file='/portable/Cache/comfy-validation/kornia.png';Image.new('RGB',(8,8),(1,2,3)).save(file)
pixels=kornia.io.load_image(file,kornia.io.ImageLoadType.RGB8)
assert tuple(pixels.shape)==(3,8,8),pixels.shape
kornia.io.write_image('/portable/Cache/comfy-validation/kornia-output.png',pixels)
assert Image.open('/portable/Cache/comfy-validation/kornia-output.png').size==(8,8)
print('Portable Kornia Rust 0.1.10 image API and filter computation passed')
'''
verified=subprocess.run([str(python_path(ROOT)),'-B','-I','-X','faulthandler','-c',fixed],capture_output=True,text=True,timeout=25)
assert verified.returncode==0,excerpt(verified.stderr,4500)
print(verified.stdout,flush=True)
profile={'backend':'cpu','max_memory_bytes':3*1024**3,'min_free_ram_bytes':512*1024**2}
with session(profile,port=8189,extra_args=['--disable-all-custom-nodes',
    '--user-directory',str(work/'user'),'--output-directory',str(work/'output'),'--input-directory',str(work/'input'),
    '--temp-directory',str(work/'temp'),'--disable-metadata']) as owned:
    assert (owned['job'].linux.group/'memory.max').read_text().strip()==str(profile['max_memory_bytes'])
    with urllib.request.urlopen('http://127.0.0.1:8189/object_info',timeout=2) as response:nodes=json.load(response)
    assert 'KSampler' in nodes and 'WanVaceToVideo' in nodes
assert owned['process'].poll() is not None
print('Gated Linux ComfyUI CPU server, VACE nodes, 3 GiB memory ceiling and stop passed')
""",
 'science':"""
from scientific_tool_bridge import _activate
_activate()
import numpy as np,scipy,sympy,rdkit,openmm,cadquery,gmsh
from rdkit import Chem
assert Chem.MolFromSmiles('CCO').GetNumAtoms()==3
assert int(sympy.integrate(sympy.Symbol('x'),(sympy.Symbol('x'),0,2)))==2
system=openmm.System();system.addParticle(1)
context=openmm.Context(system,openmm.VerletIntegrator(.001),openmm.Platform.getPlatformByName('CPU'))
context.setPositions([[0,0,0]])
assert context.getState(getEnergy=True).getKineticEnergy()._value==0
assert cadquery.Workplane('XY').box(1,2,3).val().Volume()>5.99
gmsh.initialize();gmsh.finalize()
print('science: symbolic math, molecule, CPU simulation, CAD and mesher passed')
""",
 'ml-imports':"""
from linux_ml import activate
activate(backend='cpu')
import torch,torchvision,torchaudio,diffusers,transformers,onnxruntime,open_clip,cv2,numba,comfy_aimdo,comfy_kitchen
from qwen_tts import Qwen3TTSModel
assert float((torch.ones(2)@torch.ones(2)))==2
assert torchvision.ops.nms(torch.tensor([[0.,0.,1.,1.]]),torch.tensor([1.]),.5).tolist()==[0]
from musetalk_amd_entry import activate as muse
muse()
from musetalk.models.unet import PositionalEncoding
from musetalk.utils.audio_processor import AudioProcessor
from mmaudio_amd_entry import activate as audio
audio()
from mmaudio_staged import generate
from acestep_amd_entry import activate as music,import_api
music();import_api()
print('CPU Torch/vision/audio, Qwen, MuseTalk, MMAudio and ACE-Step imports passed')
from linux_ml import probe
assert probe(backend='cpu')['compute_ok']
print('Isolated Linux ML subprocess probe passed')
""",
 'piper':"""
from piper_bridge import synthesize
result=synthesize('Portal AI portable Linux voice test.')
assert result['duration_seconds']>0
print(result)
""",
 'native-image':"""
from sdcpp_bridge import executable,run_generation,validate_png
from media_policy import SD15
exe=executable(ROOT,'cpu')
def command(out):return [str(exe),'-m',str(ROOT/SD15),'-p','a blue teapot','-W','128','-H','128','--steps','2','--rng','cpu','-t','2','-o',str(out)]
result=run_generation({'engine':'sdcpp-cpu','backend':'cpu','max_memory_bytes':3*1024**3},command,lambda p:validate_png(p,128,128),timeout=180)
print(result)
""",
}

def main():
    if len(sys.argv)>1:
        exec(CASES[sys.argv[1]],dict(globals()));return
    checks=[]
    selected=os.environ.get('PORTALAI_LINUX_TEST_CASES','').split(',') if os.environ.get('PORTALAI_LINUX_TEST_CASES') else list(CASES)
    for name in selected:
        cp=subprocess.run([str(python_path(ROOT)),'-B','-I',str(__file__),name],capture_output=True,text=True,timeout=210)
        checks.append({'name':name,'passed':cp.returncode==0,'stdout':cp.stdout[-2000:],'stderr':excerpt(cp.stderr,4500)})
        print('PORTAL_MEDIA_CHECK='+json.dumps(checks[-1]),flush=True)
    print('PORTAL_PACKAGING_RESULT='+json.dumps({'passed':all(c['passed'] for c in checks),'checks':checks,
         'scope':'Real offline Linux CPU guest; no physical AMD/NVIDIA or nested KVM validation'}),flush=True)
if __name__=='__main__':main()
