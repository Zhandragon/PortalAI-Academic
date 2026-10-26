/* Native, no-CRT Windows x64 entry. Build tools are not required on recipients. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>

static WCHAR root[32768], python[32768], script[32768], command[32768], mutex_name[96];
static STARTUPINFOW startup;
static PROCESS_INFORMATION child;

void WINAPI PortalEntry(void) {
    DWORD count=GetModuleFileNameW(NULL,root,32768), code=1;
    int argc=0; LPWSTR *argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    BOOL check=argc==2 && lstrcmpW(argv[1],L"--check")==0;
    if (!count || count>=12000) goto failed;
    while(count && root[count-1]!=L'\\') --count;
    if(!count) goto failed;
    root[count-1]=0;
    lstrcpyW(python,root);lstrcatW(python,L"\\Runtime\\BootstrapPython\\pythonw.exe");
    lstrcpyW(script,root);lstrcatW(script,L"\\ControlCenter\\control_center_bootstrap.py");
    if(GetFileAttributesW(python)==INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script)==INVALID_FILE_ATTRIBUTES) goto failed;
    if(check) ExitProcess(0);
    if(argc!=1) goto failed;
    {
        unsigned long long hash=14695981039346656037ULL;
        DWORD i=0;
        for(;root[i];++i) { WCHAR c=root[i];if(c>=L'A'&&c<=L'Z')c+=32;hash^=c;hash*=1099511628211ULL; }
        wsprintfW(mutex_name,L"Local\\PortalAI.GUI.%08x%08x",(DWORD)(hash>>32),(DWORD)hash);
        HANDLE mutex=CreateMutexW(NULL,FALSE,mutex_name);
        if(!mutex) goto failed;
        if(GetLastError()==ERROR_ALREADY_EXISTS) {
            MessageBoxW(NULL,L"PortalAI is already open for this portable folder. Check its taskbar or notification-area icon.",L"PortalAI",MB_OK|MB_ICONINFORMATION);
            CloseHandle(mutex);ExitProcess(0);
        }
        lstrcpyW(command,L"\"");lstrcatW(command,python);lstrcatW(command,L"\" -B -I \"");lstrcatW(command,script);lstrcatW(command,L"\"");
        startup.cb=sizeof(startup);
        if(!CreateProcessW(python,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,root,&startup,&child)) {
            CloseHandle(mutex);goto failed;
        }
        CloseHandle(child.hThread);WaitForSingleObject(child.hProcess,INFINITE);
        GetExitCodeProcess(child.hProcess,&code);CloseHandle(child.hProcess);CloseHandle(mutex);
        if(code) MessageBoxW(NULL,L"PortalAI could not finish starting or exited with an error. See ControlCenter\\PortableAI_Crash.log on this SSD.",L"PortalAI",MB_OK|MB_ICONERROR);
        ExitProcess(code);
    }
failed:
    if(!check) MessageBoxW(NULL,L"PortalAI could not start. Keep PortalAI.exe in the portable root beside Runtime and ControlCenter. Check the bundled Python and antivirus quarantine if a file is missing.",L"PortalAI",MB_OK|MB_ICONERROR);
    ExitProcess(1);
}
