Option Explicit

' PortableAI v15.131 stable portable startup wrapper.
' This file lives in PortableAI\Launchers and resolves the root from its own path.

Dim shell, fso, root, launcher, py, gui, cmd, refresh
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
launcher = FindNewestVersionedLauncher(root)

' Refresh the .lnk target/icon opportunistically so a copied/moved PortableAI tree
' repairs its shortcut the next time this wrapper is run directly.
refresh = root & "\Tools\Create_PortableAI_Shortcut.vbs"
If fso.FileExists(refresh) Then
    shell.Run "wscript.exe " & Quote(refresh) & " " & Quote(root), 0, False
End If

If Len(launcher) > 0 Then
    shell.Run "wscript.exe " & Quote(launcher), 0, False
    WScript.Quit 0
End If

' Fallback: launch the current Control Center directly with the portable runtime.
gui = root & "\ControlCenter\PortableAI_GUI.py"
py = FirstExisting(Array( _
    root & "\Runtime\BootstrapPython\pythonw.exe", _
    root & "\Runtime\BootstrapPython\python.exe", _
    root & "\Runtime\Python312\pythonw.exe", _
    root & "\Runtime\Python312\python.exe" _
))

If Len(py) = 0 Or Not fso.FileExists(gui) Then
    MsgBox "PortableAI could not locate its current launcher or Control Center runtime.", 16, "PortableAI"
    WScript.Quit 2
End If

cmd = Quote(py) & " " & Quote(gui) & " --root " & Quote(root)
shell.Run cmd, 0, False

Function Quote(s)
    Quote = Chr(34) & s & Chr(34)
End Function

Function FirstExisting(items)
    Dim i
    FirstExisting = ""
    For i = 0 To UBound(items)
        If fso.FileExists(items(i)) Then
            FirstExisting = items(i)
            Exit Function
        End If
    Next
End Function

Function FindNewestVersionedLauncher(portableRoot)
    Dim folder, file, n, bestPath, bestDate
    FindNewestVersionedLauncher = ""
    bestPath = ""
    bestDate = #1/1/1980#
    On Error Resume Next
    Set folder = fso.GetFolder(portableRoot)
    If Err.Number <> 0 Then
        Err.Clear
        Exit Function
    End If
    On Error GoTo 0

    For Each file In folder.Files
        n = LCase(file.Name)
        If Right(n, 4) = ".vbs" Then
            If InStr(n, "portableai") > 0 And InStr(n, "launcher") > 0 Then
                If file.DateLastModified >= bestDate Then
                    bestDate = file.DateLastModified
                    bestPath = file.Path
                End If
            End If
        End If
    Next
    FindNewestVersionedLauncher = bestPath
End Function
