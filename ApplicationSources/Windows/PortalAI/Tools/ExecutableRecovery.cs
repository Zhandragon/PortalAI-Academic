// Offline repair independent of PortalAI.exe and bundled Python. No AV changes.
using System;
using System.IO;
using System.IO.Compression;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class RecoveryFile { public string path; public string sha256; public long bytes; }
class RecoveryManifest { public int version; public RecoveryFile[] files; }
static class ExecutableRecovery {
    const string Folder="Maintenance/ExecutableRecovery/";
    static string root;
    static string Safe(string rel) {
        if(String.IsNullOrEmpty(rel)||rel.StartsWith("/")||rel.Contains("\\")||rel.Contains(":"))throw new Exception("Invalid recovery path");
        string current=root;
        foreach(string part in rel.Split('/')) {
            if(part==""||part=="."||part==".."||part.EndsWith(".")||part.EndsWith(" ")||Regex.IsMatch(part,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",RegexOptions.IgnoreCase))throw new Exception("Invalid recovery path");
            current=Path.Combine(current,part);
            try { if((File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new Exception("Recovery does not follow linked paths"); }
            catch(FileNotFoundException){} catch(DirectoryNotFoundException){}
        }
        if(!Path.GetFullPath(current).StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Path escapes installation");
        return current;
    }
    static bool Eligible(string name) {
        if(name=="PortalAI.exe"||name=="Repair PortalAI.exe")return true;
        if(!Regex.IsMatch(name,@"^(Runtime|Runtimes|LLM|Image|ImageNative|Voice|Tools|Science|Scientific|ComfyUI|MMAudio|MuseTalk|ACE-Step|Music|MusicUnderstanding|Generative|Video|SpeechToText)/"))return false;
        if(Regex.IsMatch(name,@"(^|/)(Cache|Data|Private|Downloads|ExecutableRecovery)/",RegexOptions.IgnoreCase))return false;
        return name.EndsWith(".exe",StringComparison.OrdinalIgnoreCase)||
            (Regex.IsMatch(name,@"^(LLM/backends/|ImageNative/backends/|Runtime/BootstrapPython/)")&&name.EndsWith(".dll",StringComparison.OrdinalIgnoreCase));
    }
    static string Hash(Stream input) {
        using(var sha=SHA256.Create()) {
            byte[] buffer=new byte[1048576];long total=0;int count;
            while((count=input.Read(buffer,0,buffer.Length))>0){total+=count;if(total>1073741824)throw new Exception("Recovery stream exceeds limit");sha.TransformBlock(buffer,0,count,buffer,0);}
            sha.TransformFinalBlock(new byte[0],0,0);
            return BitConverter.ToString(sha.Hash).Replace("-","").ToLowerInvariant();
        }
    }
    static string HashFile(string path) {using(var input=File.OpenRead(path))return Hash(input);}
    static RecoveryFile[] Read() {
        string manifest=Safe(Folder+"manifest.json");
        if(!File.Exists(manifest))throw new Exception("No verified backup inventory. Use the official update handoff or review your antivirus quarantine.");
        if(new FileInfo(manifest).Length>8388608)throw new Exception("Recovery manifest exceeds limit");
        var serializer=new JavaScriptSerializer {MaxJsonLength=8388608};
        var data=serializer.Deserialize<RecoveryManifest>(File.ReadAllText(manifest));
        if(data==null||data.version!=1||data.files==null||data.files.Length>20000)throw new Exception("Invalid recovery inventory");
        var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var row in data.files) {
            Safe(row.path);
            if(!Eligible(row.path)||!seen.Add(row.path)||row.bytes<=0||row.bytes>1073741824||!Regex.IsMatch(row.sha256??"",@"^[a-f0-9]{64}$"))throw new Exception("Invalid recovery fingerprint");
        }
        return data.files;
    }
    static bool Missing(RecoveryFile row) {string p=Safe(row.path);return !File.Exists(p)&&!Directory.Exists(p);}
    static string Restore(RecoveryFile[] rows) {
        var restored=new List<string>();var errors=new List<string>();
        foreach(var row in rows) {
            string temporary=null;
            try {
                if(!Missing(row))throw new Exception("Target already exists; left unchanged");
                string archive=Safe(Folder+row.sha256+".zip");
                if(new FileInfo(archive).Length>row.bytes+1048576)throw new Exception("Backup exceeds limit");
                using(var zip=ZipFile.OpenRead(archive)) {
                    if(zip.Entries.Count!=1||zip.Entries[0].FullName!="file"||zip.Entries[0].Length!=row.bytes)throw new Exception("Backup inventory mismatch");
                    using(var input=zip.Entries[0].Open())if(Hash(input)!=row.sha256)throw new Exception("Backup checksum mismatch");
                    temporary=Safe(Folder+"repair-"+Guid.NewGuid().ToString("N")+".tmp");
                    using(var input=zip.Entries[0].Open())using(var output=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                        byte[] buffer=new byte[1048576];long total=0;int count;
                        while((count=input.Read(buffer,0,buffer.Length))>0){total+=count;if(total>row.bytes)throw new Exception("Backup stream exceeds limit");output.Write(buffer,0,count);}
                        if(total!=row.bytes)throw new Exception("Truncated backup");output.Flush(true);
                    }
                }
                if(HashFile(temporary)!=row.sha256)throw new Exception("Repair staging checksum mismatch");
                string target=Safe(row.path);Directory.CreateDirectory(Path.GetDirectoryName(target));
                File.Move(temporary,target);temporary=null; // Atomic, refuses any existing target.
                if(HashFile(target)!=row.sha256)throw new Exception("Restored file changed or disappeared; review antivirus alert");
                restored.Add(row.path);
            } catch(Exception exc) {errors.Add(row.path+": "+exc.Message);}
            finally {if(temporary!=null&&File.Exists(temporary))File.Delete(temporary);}
        }
        if(errors.Count>0)Environment.ExitCode=1;
        return "Restored "+restored.Count+" file(s). Re-enable antivirus protection now.\r\nNo engine or mission was started.\r\n\r\n"+String.Join("\r\n",restored)+"\r\n"+String.Join("\r\n",errors);
    }
    static bool Confirm(RecoveryFile[] missing) {
        using(var form=new Form {Text="PortalAI — missing executables",Width=780,Height=600,StartPosition=FormStartPosition.CenterScreen}) {
            var box=new TextBox {Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,Font=new System.Drawing.Font("Segoe UI",10)};
            box.Text="Runtime files are missing. Antivirus interference is possible but not confirmed by this standalone tool.\r\n\r\nReview your antivirus alert. If you trust this installation, temporarily turn off the relevant shield and click Proceed. Only checksum-verified installation backups will be restored. A checksum is not a malware verdict. Re-enable protection immediately afterward. If the file is quarantined again, review the detection with the vendor.\r\n\r\nNo engine or mission will be started.\r\n\r\n"+String.Join("\r\n",missing.Select(r=>r.path));
            var bar=new FlowLayoutPanel {Dock=DockStyle.Bottom,Height=50};
            var proceed=new Button {Text="Proceed",Width=130,DialogResult=DialogResult.OK};
            var cancel=new Button {Text="Cancel",Width=130,DialogResult=DialogResult.Cancel};
            bar.Controls.Add(proceed);bar.Controls.Add(cancel);form.Controls.Add(box);form.Controls.Add(bar);form.CancelButton=cancel;
            return form.ShowDialog()==DialogResult.OK;
        }
    }
    [STAThread] static int Main(string[] args) {
        bool check=args.Contains("--check"),restore=args.Contains("--restore");
        try {
            root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            int index=Array.IndexOf(args,"--root");if(index>=0)root=Path.GetFullPath(args[index+1]).TrimEnd(Path.DirectorySeparatorChar);
            var rows=Read();var missing=rows.Where(Missing).ToArray();
            if(check){Console.WriteLine(new JavaScriptSerializer().Serialize(new {registered=rows.Length,missing=missing.Select(r=>r.path).ToArray()}));return 0;}
            if(!restore){Application.EnableVisualStyles();if(missing.Length>0&&!Confirm(missing))return 0;}
            string result=missing.Length==0?"All registered runtime files are present.":Restore(missing);
            if(restore)Console.WriteLine(result);else MessageBox.Show(result,"PortalAI recovery");
            return Environment.ExitCode;
        } catch(Exception exc) {
            string text=exc.Message+"\r\nRe-enable antivirus protection if you paused it.";
            if(check||restore)Console.Error.WriteLine(text);else MessageBox.Show(text,"PortalAI recovery");return 1;
        }
    }
}
