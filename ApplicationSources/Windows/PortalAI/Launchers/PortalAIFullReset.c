#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#include <windows.h>
#include <wchar.h>

static int parent_folder(WCHAR *path) {
    WCHAR *slash=wcsrchr(path,L'\\');
    if(!slash)return 0;
    if(slash==path+2 && path[1]==L':')slash[1]=0;
    else *slash=0;
    return 1;
}
static const WCHAR *folder_name(const WCHAR *path) {
    const WCHAR *slash=wcsrchr(path,L'\\');
    return slash ? slash+1 : path;
}
static void join_path(WCHAR *dest,const WCHAR *root,const WCHAR *relative) {
    lstrcpyW(dest,root);
    if(dest[lstrlenW(dest)-1]!=L'\\')lstrcatW(dest,L"\\");
    lstrcatW(dest,relative);
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,PWSTR arguments,int show) {
    WCHAR root[32768],python[32768],script[32768],command[32768];
    STARTUPINFOW startup={0};PROCESS_INFORMATION child={0};DWORD code=1;
    DWORD n=GetModuleFileNameW(NULL,root,32768);
    if(!n || n>12000 || (arguments && arguments[0])) goto fail;
    if(!parent_folder(root))goto fail;
    /* Support the requested Utilities layout and the original root layout.
       Never search another drive or consult a machine-wide saved path. */
    if(lstrcmpiW(folder_name(root),L"PortalAI-Reset")==0) {
        if(!parent_folder(root) || lstrcmpiW(folder_name(root),L"Utilities")!=0)goto fail;
        if(!parent_folder(root))goto fail;
    }
    join_path(python,root,L"PortalAI\\Runtime\\BootstrapPython\\pythonw.exe");
    join_path(script,root,L"PortalAI\\Tools\\portalai_full_reset.py");
    if(GetFileAttributesW(python)==INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script)==INVALID_FILE_ATTRIBUTES)goto fail;
    lstrcpyW(command,L"\"");lstrcatW(command,python);lstrcatW(command,L"\" -I -B -X utf8 \"");lstrcatW(command,script);lstrcatW(command,L"\"");
    startup.cb=sizeof(startup);
    if(!CreateProcessW(python,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,root,&startup,&child))goto fail;
    CloseHandle(child.hThread);WaitForSingleObject(child.hProcess,INFINITE);
    GetExitCodeProcess(child.hProcess,&code);CloseHandle(child.hProcess);
    if(code)MessageBoxW(NULL,L"The reset window could not finish. No success is assumed. Keep the drive connected and this launcher in Utilities\\PortalAI-Reset (or at the portable root).",L"PortalAI Full Reset",MB_OK|MB_ICONERROR);
    return (int)code;
fail:
    MessageBoxW(NULL,L"Keep PortalAIFullReset.exe in Utilities\\PortalAI-Reset or at the portable root containing PortalAI. This tool accepts no command-line reset option.",L"PortalAI Full Reset",MB_OK|MB_ICONERROR);
    return 1;
}
