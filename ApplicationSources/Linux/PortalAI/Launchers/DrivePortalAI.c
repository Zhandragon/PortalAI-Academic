/* Drive-level entry. Only Windows system DLLs are required on recipients. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
static WCHAR drive[32768], root[32768], exe[32768], command[32768];
static STARTUPINFOW startup;
static PROCESS_INFORMATION child;
static BOOL candidate(LPCWSTR name) {
    lstrcpyW(root,drive);lstrcatW(root,name);
    lstrcpyW(exe,root);lstrcatW(exe,L"\\PortalAI.exe");
    DWORD attributes=GetFileAttributesW(exe);
    return attributes!=INVALID_FILE_ATTRIBUTES && !(attributes&FILE_ATTRIBUTE_DIRECTORY);
}
void WINAPI PortalEntry(void) {
    DWORD count=GetModuleFileNameW(NULL,drive,32768), code=1;
    int argc=0; LPWSTR *argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    BOOL check=argc==2 && lstrcmpW(argv[1],L"--check")==0;
    if(!count || count>=12000 || (argc!=1 && !check)) goto failed;
    while(count && drive[count-1]!=L'\\') --count;
    if(!count) goto failed;
    drive[count]=0;
    BOOL windows=candidate(L"PortalAI Windows"), modern=candidate(L"PortalAI"), legacy=candidate(L"PortableAI");
    if((windows?1:0)+(modern?1:0)+(legacy?1:0)!=1) goto failed; /* Refuse missing or ambiguous installations. */
    candidate(windows?L"PortalAI Windows":(modern?L"PortalAI":L"PortableAI"));
    lstrcpyW(command,L"\"");lstrcatW(command,exe);lstrcatW(command,L"\"");
    if(check) lstrcatW(command,L" --check");
    startup.cb=sizeof(startup);
    if(!CreateProcessW(exe,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,root,&startup,&child)) goto failed;
    CloseHandle(child.hThread);WaitForSingleObject(child.hProcess,INFINITE);
    GetExitCodeProcess(child.hProcess,&code);CloseHandle(child.hProcess);ExitProcess(code);
failed:
    if(!check) MessageBoxW(NULL,L"Keep this launcher beside exactly one PortalAI Windows, PortalAI, or PortableAI folder containing PortalAI.exe. The folder and launcher must remain on the same drive.",L"PortalAI",MB_OK|MB_ICONERROR);
    ExitProcess(1);
}
