// PortalAI owned microphone capture using Windows Voice Capture DSP.
// Source-mode DSP synchronizes microphone and the actual default speaker stream.
// https://learn.microsoft.com/windows/win32/medfound/voicecapturedmo
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <initguid.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <wmcodecdsp.h>
#include <mediaobj.h>
#include <uuids.h>
#include <mmsystem.h>
#include <io.h>
#include <fcntl.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <stdexcept>

static void check(HRESULT hr,const char* operation) {
    if(FAILED(hr)) {char text[200];sprintf_s(text,"%s failed: HRESULT 0x%08lx",operation,(unsigned long)hr);throw std::runtime_error(text);}
}
template<class T> struct Com {
    T* p=nullptr;~Com(){if(p)p->Release();}
    T** out(){return &p;} T* operator->(){return p;}
};
class Buffer:public IMediaBuffer {
    LONG refs=1;DWORD length=0;std::vector<BYTE> bytes;
public:
    Buffer():bytes(32000){}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id,void** out) override {
        if(!out)return E_POINTER;*out=nullptr;
        if(id==IID_IUnknown || id==__uuidof(IMediaBuffer)){*out=this;AddRef();return S_OK;}return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override{return InterlockedIncrement(&refs);}
    ULONG STDMETHODCALLTYPE Release() override{ULONG n=InterlockedDecrement(&refs);if(!n)delete this;return n;}
    HRESULT STDMETHODCALLTYPE SetLength(DWORD n) override{if(n>bytes.size())return E_INVALIDARG;length=n;return S_OK;}
    HRESULT STDMETHODCALLTYPE GetMaxLength(DWORD* n) override{if(!n)return E_POINTER;*n=(DWORD)bytes.size();return S_OK;}
    HRESULT STDMETHODCALLTYPE GetBufferAndLength(BYTE** b,DWORD* n) override{if(b)*b=bytes.data();if(n)*n=length;return S_OK;}
};
// Keep the default render endpoint active even during listening. Silence is
// queued on an owned WinMM handle; no host audio setting is modified.
struct SilentRender {
    HWAVEOUT handle=nullptr;WAVEHDR headers[4]={};short samples[4][1600]={};
    SilentRender() {
        WAVEFORMATEX format={WAVE_FORMAT_PCM,1,16000,32000,2,16,0};
        if(waveOutOpen(&handle,WAVE_MAPPER,&format,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR)throw std::runtime_error("Default speaker could not open");
        for(int i=0;i<4;i++){headers[i].lpData=(LPSTR)samples[i];headers[i].dwBufferLength=sizeof(samples[i]);
            if(waveOutPrepareHeader(handle,&headers[i],sizeof(WAVEHDR)) || waveOutWrite(handle,&headers[i],sizeof(WAVEHDR)))throw std::runtime_error("Speaker silence queue failed");}
    }
    void tick(){for(auto& h:headers)if(h.dwFlags&WHDR_DONE){if(waveOutWrite(handle,&h,sizeof(h)))throw std::runtime_error("Speaker disconnected");}}
    ~SilentRender(){if(handle){waveOutReset(handle);for(auto& h:headers)waveOutUnprepareHeader(handle,&h,sizeof(h));waveOutClose(handle);}}
};
static void set_int(IPropertyStore* props,const PROPERTYKEY& key,int value) {
    PROPVARIANT v;PropVariantInit(&v);v.vt=VT_I4;v.lVal=value;check(props->SetValue(key,v),"Set DSP property");
}
static int microphone_index(const std::wstring& requested) {
    if(requested==L"auto")return -1;
    Com<IMMDeviceEnumerator> enumerator;check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_INPROC_SERVER,__uuidof(IMMDeviceEnumerator),(void**)enumerator.out()),"Enumerate microphones");
    Com<IMMDeviceCollection> collection;check(enumerator->EnumAudioEndpoints(eCapture,DEVICE_STATE_ACTIVE,collection.out()),"Microphone collection");
    UINT count=0;check(collection->GetCount(&count),"Microphone count");int match=-1;
    for(UINT i=0;i<count;i++){
        Com<IMMDevice> device;Com<IPropertyStore> props;check(collection->Item(i,device.out()),"Microphone item");check(device->OpenPropertyStore(STGM_READ,props.out()),"Microphone properties");
        PROPVARIANT name;PropVariantInit(&name);check(props->GetValue(PKEY_Device_FriendlyName,&name),"Microphone name");
        bool matches=name.vt==VT_LPWSTR && _wcsnicmp(name.pwszVal,requested.c_str(),requested.size())==0;PropVariantClear(&name);
        if(matches){if(match!=-1)throw std::runtime_error("Microphone name is ambiguous; select the default microphone for echo cancellation");match=(int)i;}
    }
    if(match<0)throw std::runtime_error("Selected microphone was not found among active Windows endpoints");return match;
}
int wmain(int argc,wchar_t** argv) {
    if(argc!=3 || wcscmp(argv[1],L"--capture")){fprintf(stderr,"Internal PortalAI capture helper: --capture auto|microphone-name\n");return 2;}
    // The parent attaches this process to a kill-on-close job before opening gate.
    char gate[8]={};if(!fgets(gate,sizeof(gate),stdin) || strcmp(gate,"go\n"))return 3;
    HRESULT initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);if(FAILED(initialized))return 4;
    int code=0;
    try {
        int microphone=microphone_index(argv[2]);
        Com<IMediaObject> dsp;check(CoCreateInstance(__uuidof(CWMAudioAEC),nullptr,CLSCTX_INPROC_SERVER,__uuidof(IMediaObject),(void**)dsp.out()),"Create Windows echo cancellation");
        Com<IPropertyStore> properties;check(dsp->QueryInterface(__uuidof(IPropertyStore),(void**)properties.out()),"DSP properties");
        set_int(properties.p,MFPKEY_WMAAECMA_SYSTEM_MODE,0); // SINGLE_CHANNEL_AEC
        set_int(properties.p,MFPKEY_WMAAECMA_DEVICE_INDEXES,(int)(0xffff0000u|((unsigned)microphone&0xffffu)));
        WAVEFORMATEX format={WAVE_FORMAT_PCM,1,16000,32000,2,16,0};DMO_MEDIA_TYPE media={};
        media.majortype=MEDIATYPE_Audio;media.subtype=MEDIASUBTYPE_PCM;media.bFixedSizeSamples=TRUE;media.bTemporalCompression=FALSE;media.lSampleSize=2;
        media.formattype=FORMAT_WaveFormatEx;media.cbFormat=sizeof(format);media.pbFormat=(BYTE*)&format;
        check(dsp->SetOutputType(0,&media,0),"DSP 16 kHz mono output");
        SilentRender render;check(dsp->AllocateStreamingResources(),"Allocate echo capture");
        Com<IMediaBuffer> buffer;buffer.p=new Buffer();
        _setmode(_fileno(stdout),_O_BINARY);setvbuf(stdout,nullptr,_IONBF,0);
        if(fwrite("PAEC",1,4,stdout)!=4)throw std::runtime_error("Capture parent closed");
        ULONGLONG last=GetTickCount64();
        while(true){
            render.tick();buffer->SetLength(0);DMO_OUTPUT_DATA_BUFFER output={};output.pBuffer=buffer.p;DWORD status=0;
            check(dsp->ProcessOutput(0,1,&output,&status),"Echo capture processing");
            BYTE* bytes=nullptr;DWORD length=0;buffer->GetBufferAndLength(&bytes,&length);
            if(length){if(fwrite(bytes,1,length,stdout)!=length)break;last=GetTickCount64();}
            if(GetTickCount64()-last>5000)throw std::runtime_error("Echo capture produced no audio; check microphone and default speaker");
            if(!(output.dwStatus&DMO_OUTPUT_DATA_BUFFERF_INCOMPLETE))Sleep(10);
        }
        dsp->FreeStreamingResources();
    }catch(const std::exception& e){fprintf(stderr,"%s\n",e.what());code=10;}
    CoUninitialize();return code;
}
