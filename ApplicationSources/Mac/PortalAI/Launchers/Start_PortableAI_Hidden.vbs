Option Explicit
Dim shell, fso, root, script, py, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Dim paiEnv, paiLaunchDir, paiRootDir, paiBootstrap
Set paiEnv = shell.Environment("PROCESS")
paiLaunchDir = fso.GetParentFolderName(WScript.ScriptFullName)
paiRootDir = fso.GetParentFolderName(paiLaunchDir)
paiBootstrap = fso.BuildPath(paiRootDir, "Runtime\BootstrapPython")
If fso.FileExists(fso.BuildPath(paiBootstrap, "python.exe")) Then paiEnv("PATH") = paiBootstrap & ";" & paiEnv("PATH")
If WScript.Arguments.Count > 0 Then
    root = WScript.Arguments(0)
Else
    root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
End If
script = root & "\Launchers\Start_PortableAI_Controller.py"
If Not fso.FileExists(script) Then
    WScript.Quit 2
End If
py = FindPython(shell)
If Len(py) = 0 Then
    WScript.Quit 3
End If
cmd = Quote(py) & " " & Quote(script) & " --root " & Quote(root)
shell.Run cmd, 0, False

Function Quote(s)
    Quote = Chr(34) & s & Chr(34)
End Function

Function FindPython(sh)
    Dim e, line
    On Error Resume Next
    Set e = sh.Exec("cmd.exe /d /c where.exe pythonw.exe 2>nul")
    If Err.Number = 0 Then
        If Not e.StdOut.AtEndOfStream Then line = Trim(e.StdOut.ReadLine) Else line = ""
        If Len(line) > 0 Then FindPython = line: Exit Function
    End If
    Err.Clear
    Set e = sh.Exec("cmd.exe /d /c where.exe python.exe 2>nul")
    If Err.Number = 0 Then
        If Not e.StdOut.AtEndOfStream Then line = Trim(e.StdOut.ReadLine) Else line = ""
        If Len(line) > 0 Then FindPython = line: Exit Function
    End If
    On Error GoTo 0
    FindPython = ""
End Function
