using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class Item {
    internal string Name, Hash; internal long Bytes;
    internal Item(string name, long bytes, string hash) { Name=name; Bytes=bytes; Hash=hash; }
}
internal static class Bootstrap {
    internal const string Source = "https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.29-Desktop-r51";
    internal const string Archive = "PortalAI-Academic-Windows-Installer-2026.10.29-Desktop-r51-suite.zip";
    internal const string ArchiveHash = "6cf64c5419af450705357119620986e60b31ad7197b0b73929d9c724f453522a";
    internal const string Owner = "PortalAI-Academic-bootstrap-20261029-Desktop-r51-Windows";
    internal static readonly Item[] Parts = new Item[] { new Item("PortalAI-Academic-Windows-Installer-2026.10.29-Desktop-r51-suite.zip", 542562829L, "6cf64c5419af450705357119620986e60b31ad7197b0b73929d9c724f453522a") };
    internal static readonly Item[] Files = new Item[] { new Item("PortalAI-Academic-Install.exe", 11603456L, "70ba5107d292e3458249a2d3fabc0055abdc79e865217ce7fa822a93172e9fcd"),
new Item("release.json", 138786249L, "2d6c94e75ee233415d323afa6c6fe8a697cde11b67a1858ec87b4b05161091e3"),
new Item("payload.zip", 300190697L, "1d7c2ae0094d1de9febc49b3926d07dad57b1c924eade36c25afaa66092df4b3"),
new Item("START_HERE.txt", 4570L, "758758f3b9c91b1d6060df0419d72d33fc83db25a1d5d0f5677a6eedbdbdcd76"),
new Item("storage-plan.json", 190024L, "bd041cd2251e1d7b5de6b57674ee27997488720d81f313f8b45ad7312a19cc93"),
new Item("sox-14.4.2-win32.zip", 2651143L, "8072cc147cf1a3b3713b8b97d6844bb9389e211ab9e1101e432193fad6ae6662"),
new Item("qemu-w64-setup-20260811.exe", 206615928L, "f98a8aeb5f7faea9765b6dee28316c266cd179d80354a2fed8e50176f9a2e59f"),
new Item("PACKAGE_SHA256.json", 1312L, "cf612ca7ab2d0075c0a07cffe285275f78dd19995f11a593713afe02d0b79a28"),
new Item("upgrade.json", 1050L, "32c43b40b4ea371da919593987138a2485314eea103b4e0a599acfbb9127436a"),
new Item("suite-catalog.json", 4338L, "b13352f1ac78d1cdd6ff7ea40a5c3c399cc8b4fc31b1fe100183bf9aa51e3eea") };
    internal static string Digest(string path) {
        using (var hash = SHA256.Create()) using (var stream = File.OpenRead(path))
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    internal static bool Valid(string path, Item item) {
        return File.Exists(path) && new FileInfo(path).Length == item.Bytes && Digest(path) == item.Hash;
    }
    internal static void Check(bool cancel) { if (cancel) throw new OperationCanceledException("Download cancelled. Verified parts can be reused next time."); }
    internal static void Publish(Action action, Func<bool> cancelled) {
        // File scanners can briefly hold newly downloaded or extracted files.
        for (int attempt=0; ; attempt++) {
            Check(cancelled());
            try { action(); return; }
            catch (IOException) { if (attempt>=59) throw; }
            catch (UnauthorizedAccessException) { if (attempt>=59) throw; }
            Thread.Sleep(500);
        }
    }
    internal static string Prepare(string target, Action<int,string> report, Func<bool> cancelled, bool includeInstall = true) {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        target = Path.GetFullPath(target);
        string marker = Path.Combine(target, ".portalai-academic-setup");
        if (Directory.Exists(target) && Directory.GetFileSystemEntries(target).Length > 0 &&
            (!File.Exists(marker) || File.ReadAllText(marker) != Owner))
            throw new IOException("Choose a new, empty setup folder. This folder contains unrelated files.");
        report(0, StoragePreflight.Check(target, includeInstall ? 171947246508L : 1745174425L, includeInstall ? 303966L : 14L, 0));
        Directory.CreateDirectory(target);
        if (!File.Exists(marker)) using (var writer = new StreamWriter(new FileStream(marker, FileMode.CreateNew))) writer.Write(Owner);
        using (var gate = new FileStream(Path.Combine(target, ".bootstrap.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None)) {
            string cache = Path.Combine(target, "downloads"); Directory.CreateDirectory(cache);
            long total=0, completed=0; foreach (Item item in Parts) total += item.Bytes;
            for (int index=0; index<Parts.Length; index++) {
                Item item=Parts[index]; string final=Path.Combine(cache, item.Name);
                Check(cancelled());
                if (!Valid(final, item)) {
                    Exception last = null;
                    for (int attempt=1; attempt<=3; attempt++) {
                        string temp = Path.Combine(cache, ".download-" + Guid.NewGuid().ToString("N"));
                        try {
                            report((int)(completed*85/total), "Downloading part " + (index+1) + " of " + Parts.Length + " (attempt " + attempt + ")");
                            var request=(HttpWebRequest)WebRequest.Create(Source + "/" + Uri.EscapeDataString(item.Name));
                            request.UserAgent="PortalAI-Academic-Installer/20261029-Desktop-r51";
                            request.Timeout=30000; request.ReadWriteTimeout=30000;
                            using (var response=(HttpWebResponse)request.GetResponse()) {
                                if (response.ResponseUri.Scheme != new Uri(Source).Scheme) throw new IOException("Unexpected download redirect protocol.");
                                if (response.ContentLength >= 0 && response.ContentLength != item.Bytes) throw new IOException("Incorrect server file size for " + item.Name);
                                using (var input=response.GetResponseStream()) using (var output=new FileStream(temp, FileMode.CreateNew)) {
                                    byte[] buffer=new byte[1024*1024]; int count; long received=0;
                                    while ((count=input.Read(buffer,0,buffer.Length))>0) {
                                        Check(cancelled()); received+=count;
                                        if (received>item.Bytes) throw new IOException("Download exceeded the expected size.");
                                        output.Write(buffer,0,count);
                                        report((int)((completed+received)*85/total), String.Format("Downloading part {0}/{1}: {2:F1} / {3:F1} MiB",index+1,Parts.Length,received/1048576.0,item.Bytes/1048576.0));
                                    }
                                }
                            }
                            if (!Valid(temp,item)) throw new IOException("Checksum verification failed for " + item.Name);
                            Publish(delegate { if (File.Exists(final)) File.Replace(temp,final,null); else File.Move(temp,final); },cancelled);
                            last=null; break;
                        } catch (OperationCanceledException) { throw; }
                          catch (Exception error) { last=error; if (attempt<3) Thread.Sleep(1000); }
                          finally { if (File.Exists(temp)) File.Delete(temp); }
                    }
                    if (last!=null) throw new IOException("Could not download a verified part from GitHub. Check your connection and that the pinned release asset is available. " + last.Message, last);
                }
                completed+=item.Bytes;
                report((int)(completed*85/total), "Verified part " + (index+1) + " of " + Parts.Length);
            }
            Check(cancelled()); report(88,"Reconstructing and verifying the installer...");
            string archive=Path.Combine(cache, Archive);
            if (!File.Exists(archive) || Digest(archive)!=ArchiveHash) {
                string temp=Path.Combine(cache,".assemble-"+Guid.NewGuid().ToString("N"));
                try {
                    using (var output=new FileStream(temp,FileMode.CreateNew)) foreach (Item item in Parts) {
                        Check(cancelled()); using (var input=File.OpenRead(Path.Combine(cache,item.Name))) input.CopyTo(output);
                    }
                    if (Digest(temp)!=ArchiveHash) throw new IOException("Reconstructed archive checksum failed.");
                    Publish(delegate { if (File.Exists(archive)) File.Replace(temp,archive,null); else File.Move(temp,archive); },cancelled);
                } finally { if (File.Exists(temp)) File.Delete(temp); }
            }
            string package=Path.Combine(target,"installer");
            string extractionMarker=Path.Combine(target,".extracting-verified-installer");
            if (!Directory.Exists(package) && !File.Exists(extractionMarker)) File.WriteAllText(extractionMarker,ArchiveHash);
            if (File.Exists(extractionMarker)) {
                if (File.ReadAllText(extractionMarker)!=ArchiveHash) throw new IOException("Unexpected extraction marker. Choose a new setup folder.");
                Check(cancelled()); report(93,"Extracting the verified installer...");
                // Do not rename a directory containing a newly scanned executable.
                // Only a marked incomplete extraction may replace installer files;
                // nothing can launch until every extracted file passes its hash.
                Directory.CreateDirectory(package);
                using (var zip=ZipFile.OpenRead(archive)) foreach (ZipArchiveEntry entry in zip.Entries) {
                    Check(cancelled());
                    string path=Path.GetFullPath(Path.Combine(package,entry.FullName));
                    if (!path.StartsWith(package+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe archive entry.");
                    if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                    Item expected=null; foreach(Item item in Files) if(item.Name==entry.FullName) expected=item;
                    if (expected==null) throw new IOException("Unexpected installer file.");
                    if (Valid(path,expected)) continue;
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    using (var input=entry.Open()) using (var output=new FileStream(path,FileMode.Create)) input.CopyTo(output);
                }
            }
            foreach (Item item in Files) if (!Valid(Path.Combine(package,item.Name),item))
                throw new IOException("An extracted installer file is missing or changed: " + item.Name + ". Choose a new setup folder to download a clean copy.");
            if (File.Exists(extractionMarker)) File.Delete(extractionMarker);
            Check(cancelled()); report(100,"Verified. Opening the Academic installer...");
            return Path.Combine(package,"PortalAI-Academic-Install.exe");
        }
    }
    internal static void Launch(string installer) {
        Process.Start(new ProcessStartInfo(installer) { UseShellExecute=true, WorkingDirectory=Path.GetDirectoryName(installer) });
    }
    [STAThread] public static int Main(string[] args) {
        if (args.Length==2 && args[0]=="--prepare-only") {
            try { string file=Prepare(args[1],delegate(int p,string s) { Console.WriteLine(s); },delegate {return false;}, false); Console.WriteLine(file); return 0; }
            catch(Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupForm(args.Length==1 && args[0]=="--ui-smoke")); return 0;
    }
}
internal static class PortalPaint {
    internal static System.Drawing.Drawing2D.GraphicsPath Round(RectangleF r, float radius) {
        var p = new System.Drawing.Drawing2D.GraphicsPath(); float d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
        if (d <= 0) { p.AddRectangle(r); return p; }
        p.AddArc(r.X,r.Y,d,d,180,90); p.AddArc(r.Right-d,r.Y,d,d,270,90);
        p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90); p.AddArc(r.X,r.Bottom-d,d,d,90,90); p.CloseFigure(); return p;
    }
}
internal sealed class PortalButton : Button {
    internal Color Edge = Color.FromArgb(176,134,58), Hover = Color.FromArgb(54,58,61);
    bool hovering;
    internal PortalButton() { FlatStyle=FlatStyle.Flat; FlatAppearance.BorderSize=0; UseVisualStyleBackColor=false; Height=33; Width=110; Cursor=Cursors.Hand; SetStyle(ControlStyles.OptimizedDoubleBuffer|ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint,true); }
    protected override void OnMouseEnter(EventArgs e) { hovering=true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hovering=false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnPaint(PaintEventArgs e) {
        e.Graphics.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor);
        using (var path=PortalPaint.Round(new RectangleF(1,1,Width-3,Height-3),7)) {
            using (var fill=new SolidBrush(hovering && Enabled ? Hover : BackColor)) e.Graphics.FillPath(fill,path);
            using (var pen=new Pen(Focused ? Edge : Color.FromArgb(100,Edge),Focused ? 2 : 1)) e.Graphics.DrawPath(pen,path);
        }
        TextRenderer.DrawText(e.Graphics,Text,Font,ClientRectangle,Enabled ? ForeColor : SystemColors.GrayText,TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis);
    }
}
internal sealed class PortalProgress : Control {
    internal double Fraction; internal bool Indeterminate; internal Color Accent=Color.FromArgb(88,175,193);
    readonly System.Windows.Forms.Timer animation = new System.Windows.Forms.Timer(); int offset;
    internal PortalProgress() {
        Height=15; SetStyle(ControlStyles.OptimizedDoubleBuffer|ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint,true);
        animation.Interval=40; animation.Tick+=delegate { if (Indeterminate && Visible) { offset=(offset+5)%Math.Max(1,Width+80); Invalidate(); } }; animation.Start();
    }
    protected override void OnPaint(PaintEventArgs e) {
        e.Graphics.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias; e.Graphics.Clear(Parent.BackColor);
        using (var path=PortalPaint.Round(new RectangleF(0,0,Math.Max(1,Width-1),Math.Max(1,Height-1)),6)) {
            using (var brush=new SolidBrush(BackColor))e.Graphics.FillPath(brush,path);
            var saved=e.Graphics.Save();e.Graphics.SetClip(path);
            int width=(int)(Width*Math.Max(0,Math.Min(1,Fraction)));
            using (var brush=new SolidBrush(Accent))e.Graphics.FillRectangle(brush,Indeterminate ? offset-80 : 0,0,Indeterminate ? 80 : width,Height);
            e.Graphics.Restore(saved);
        }
    }
    protected override void Dispose(bool disposing) { if(disposing)animation.Dispose();base.Dispose(disposing); }
}
internal sealed class SetupForm : Form {
    TextBox destination=new TextBox(); Label status=new Label(); PortalProgress progress=new PortalProgress();
    PortalButton theme=new PortalButton(); Label title=new Label(); bool dark=true; Color gold; Point? drag;
    PortalButton browse=new PortalButton(), start=new PortalButton(), cancel=new PortalButton(); volatile bool stop; bool busy;
    internal SetupForm(bool smoke) {
        Text="PortalAI Academic - Windows Setup"; ClientSize=new Size(780,450); MinimumSize=new Size(780,450); FormBorderStyle=FormBorderStyle.None; Padding=new Padding(8); DoubleBuffered=true; Font=new Font("Segoe UI",9F); StartPosition=FormStartPosition.CenterScreen;
        var layout=new TableLayoutPanel { Dock=DockStyle.Fill, Padding=new Padding(18), ColumnCount=1, RowCount=7 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,55));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,90)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,25));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,40)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,50));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,30)); layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
        var header=new Panel { Dock=DockStyle.Fill };
        title.Text="PortalAI Academic";title.Font=new Font("Georgia",18F,FontStyle.Bold);title.Dock=DockStyle.Fill;title.TextAlign=ContentAlignment.MiddleLeft;
        var chrome=new FlowLayoutPanel { Dock=DockStyle.Right,Width=278,FlowDirection=FlowDirection.RightToLeft,Padding=new Padding(0,7,0,0) };
        var exit=new PortalButton { Text="✕",Width=40,AccessibleName="Close installer" };
        var maximize=new PortalButton { Text="▢",Width=40,AccessibleName="Maximize or restore installer" };
        var minimize=new PortalButton { Text="—",Width=40,AccessibleName="Minimize installer" };
        theme.Width=125;theme.Click+=delegate { dark=!dark;ApplyTheme(); };
        exit.Click+=delegate { Close(); };minimize.Click+=delegate { WindowState=FormWindowState.Minimized; };
        maximize.Click+=delegate { MaximizedBounds=Screen.FromControl(this).WorkingArea;WindowState=WindowState==FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized; };
        chrome.Controls.AddRange(new Control[]{exit,maximize,minimize,theme});header.Controls.Add(title);header.Controls.Add(chrome);
        title.MouseDown+=delegate(object sender,MouseEventArgs e) { if(e.Button==MouseButtons.Left && WindowState==FormWindowState.Normal)drag=new Point(Cursor.Position.X-Left,Cursor.Position.Y-Top); };
        title.MouseMove+=delegate { if(drag.HasValue && Control.MouseButtons==MouseButtons.Left)Location=new Point(Cursor.Position.X-drag.Value.X,Cursor.Position.Y-drag.Value.Y); };
        title.MouseUp+=delegate { drag=null; };
        layout.Controls.Add(header);
        layout.Controls.Add(new Label { Dock=DockStyle.Fill, Text="Download and install PortalAI Academic for Windows.\r\n\r\nThis is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students." });
        layout.Controls.Add(new Label { Dock=DockStyle.Fill, Text="Setup folder (choose a drive with room for the application and models):" });
        var pathRow=new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=2 }; pathRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100)); pathRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,90));
        destination.Dock=DockStyle.Fill; destination.Text=Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"PortalAI Academic Windows Setup");
        browse.Text="Browse..."; browse.Click+=delegate { using(var picker=new FolderBrowserDialog()) { picker.Description="Select a parent folder for PortalAI Academic setup"; if(picker.ShowDialog()==DialogResult.OK) destination.Text=Path.Combine(picker.SelectedPath,"PortalAI Academic Windows Setup"); } };
        pathRow.Controls.Add(destination); pathRow.Controls.Add(browse); layout.Controls.Add(pathRow);
        status.Dock=DockStyle.Fill; status.Text="Downloads about 543 MB from GitHub, verifies it, and opens the full installer. Further runtime/model downloads follow."; layout.Controls.Add(status);
        progress.Dock=DockStyle.Fill; layout.Controls.Add(progress);
        var buttons=new FlowLayoutPanel { Dock=DockStyle.Fill, FlowDirection=FlowDirection.RightToLeft };
        start.Text="Download and install"; start.Width=180; cancel.Text="Cancel"; cancel.Enabled=false; buttons.Controls.Add(start); buttons.Controls.Add(cancel); layout.Controls.Add(buttons); Controls.Add(layout);ApplyTheme();
        start.Click+=async delegate {
            busy=true; stop=false; start.Enabled=browse.Enabled=destination.Enabled=false; cancel.Enabled=true;
            try {
                string target=destination.Text;
                string installer=await Task.Run(()=>Bootstrap.Prepare(target,UpdateProgress,()=>stop));
                Bootstrap.Check(stop); Bootstrap.Launch(installer); status.Text="Academic installer opened. Continue in its window.";
            } catch(Exception error) { status.Text=error.Message;  }
            finally { busy=false; start.Enabled=browse.Enabled=destination.Enabled=true; cancel.Enabled=false; }
        };
        cancel.Click+=delegate {stop=true; cancel.Enabled=false; status.Text="Cancelling...";};
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {if(busy) {e.Cancel=true; stop=true; status.Text="Cancelling download before closing...";}};
        if(smoke) {var timer=new System.Windows.Forms.Timer {Interval=300}; timer.Tick+=delegate {timer.Stop();Close();};timer.Start();}
    }
    void ApplyTheme() {
        Color bg=ColorTranslator.FromHtml(dark ? "#111315" : "#EEE7DC"),panel=ColorTranslator.FromHtml(dark ? "#1C1E20" : "#F8F3EA"),text=ColorTranslator.FromHtml(dark ? "#F2ECE2" : "#202224");
        gold=ColorTranslator.FromHtml(dark ? "#B0863A" : "#A87D32");
        PaintControls(this,bg,panel,text,ColorTranslator.FromHtml(dark ? "#2A2D2F" : "#E6DCCB"),ColorTranslator.FromHtml(dark ? "#363A3D" : "#D9CBB3"));
        progress.BackColor=panel;progress.Accent=title.ForeColor=ColorTranslator.FromHtml(dark ? "#58AFC1" : "#3E91A2");theme.Text=dark ? "Light mode" : "Dark mode";Invalidate(true);
    }
    void PaintControls(Control root,Color bg,Color panel,Color text,Color button,Color hover) {
        root.BackColor=root is TextBox ? panel : bg;root.ForeColor=text;
        var b=root as PortalButton;if(b!=null) { b.BackColor=button;b.Hover=hover;b.Edge=gold; }
        foreach(Control child in root.Controls)PaintControls(child,bg,panel,text,button,hover);
    }
    protected override void OnPaint(PaintEventArgs e) {
        base.OnPaint(e);e.Graphics.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using(var path=PortalPaint.Round(new RectangleF(2,2,Width-5,Height-5),17))using(var pen=new Pen(gold,2))e.Graphics.DrawPath(pen,path);
        using(var path=PortalPaint.Round(new RectangleF(6,6,Width-13,Height-13),13))using(var pen=new Pen(gold,1))e.Graphics.DrawPath(pen,path);
    }
    protected override void WndProc(ref Message m) {
        base.WndProc(ref m);
        if(m.Msg==0x84 && WindowState==FormWindowState.Normal) {
            Point p=PointToClient(new Point((short)(m.LParam.ToInt64()&65535),(short)((m.LParam.ToInt64()>>16)&65535)));
            bool left=p.X<8,right=p.X>=Width-8,top=p.Y<8,bottom=p.Y>=Height-8;
            int hit=top ? (left ? 13 : right ? 14 : 12) : bottom ? (left ? 16 : right ? 17 : 15) : left ? 10 : right ? 11 : 0;
            if(hit!=0)m.Result=(IntPtr)hit;
        }
    }
    void UpdateProgress(int percent,string text) { BeginInvoke((Action)delegate {progress.Fraction=Math.Max(0,Math.Min(1,percent/100.0));progress.Invalidate();status.Text=text+" (setup "+percent+"%)";}); }
}

// Shared by the native Windows installer and the Academic download launcher.
internal static class StoragePreflight {
    const long GiB = 1073741824L;
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
    static extern bool GetDiskFreeSpaceEx(string path, out ulong available, out ulong total, out ulong free);
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
    static extern bool GetVolumePathName(string path, System.Text.StringBuilder volume, int length);
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
    static extern bool GetDiskFreeSpace(string path, out uint sectors, out uint bytes, out uint free, out uint total);
    internal static string ExistingDirectory(string path) {
        string current = System.IO.Path.GetFullPath(path);
        while (!System.IO.Directory.Exists(current)) {
            if (System.IO.File.Exists(current)) throw new System.IO.IOException("Installation destination is not a directory.");
            current = System.IO.Path.GetDirectoryName(current);
            if (String.IsNullOrEmpty(current)) throw new System.IO.IOException("Cannot locate the destination volume.");
        }
        return current;
    }
    internal static long AllocationUnit(string path) {
        var volume = new System.Text.StringBuilder(32768);
        uint sectors, bytes, free, total;
        if (!GetVolumePathName(path, volume, volume.Capacity) || !GetDiskFreeSpace(volume.ToString(), out sectors, out bytes, out free, out total))
            throw new System.ComponentModel.Win32Exception(System.Runtime.InteropServices.Marshal.GetLastWin32Error(), "Cannot determine destination filesystem allocation size.");
        return checked((long)sectors * bytes);
    }
    internal static string Check(string path, long baseBytes, long fileCount, long extraBytes) {
        string probe = ExistingDirectory(path);
        ulong available, total, free;
        if (!GetDiskFreeSpaceEx(probe, out available, out total, out free))
            throw new System.ComponentModel.Win32Exception(System.Runtime.InteropServices.Marshal.GetLastWin32Error(), "Cannot determine available destination disk space.");
        long need = checked(baseBytes + fileCount * (AllocationUnit(probe) - 1) + extraBytes + GiB);
        return Compare(path, need, available);
    }
    internal static string Compare(string path, long need, ulong available) {
        string message = String.Format(System.Globalization.CultureInfo.InvariantCulture,
            "Disk space at {0}: required {1:F2} GiB; available {2:F2} GiB. Includes installed files, retained downloads, filesystem allocation and working space.", path, need/(double)GiB, available/(double)GiB);
        if ((ulong)need > available) throw new System.IO.IOException(message + String.Format(System.Globalization.CultureInfo.InvariantCulture,
            " Need {0:F2} GiB more. Choose another destination, free space, or select fewer optional components.", (need-(double)available)/GiB));
        return message;
    }
    internal static System.Collections.Generic.Dictionary<string,object> EmbeddedPlan() {
        using (var stream = System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("storage-plan.json"))
        using (var reader = new System.IO.StreamReader(stream)) {
            return new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string,object>>(reader.ReadToEnd());
        }
    }
    internal static string CheckSelection(string path, string[] selected) {
        var plan = EmbeddedPlan();
        var ids = new System.Collections.Generic.HashSet<string>(selected);
        var components = new System.Collections.Generic.Dictionary<string,System.Collections.Generic.Dictionary<string,object>>();
        foreach (object item in (System.Collections.IEnumerable)plan["components"]) {
            var c = (System.Collections.Generic.Dictionary<string,object>)item;
            string id = (string)c["id"]; components.Add(id,c);
            if (Convert.ToBoolean(c["required"])) ids.Add(id);
        }
        bool changed;
        do {
            changed=false;
            foreach (string id in new System.Collections.Generic.List<string>(ids)) {
                if (!components.ContainsKey(id)) throw new System.IO.IOException("Unknown installer component.");
                foreach (object dep in (System.Collections.IEnumerable)components[id]["depends_on"]) changed |= ids.Add((string)dep);
            }
        } while(changed);
        long installed=Convert.ToInt64(plan["payload_bytes"]), count=Convert.ToInt64(plan["payload_files"]);
        var downloads = new System.Collections.Generic.Dictionary<string,long>();
        foreach(string id in ids) {
            var c=components[id]; installed=checked(installed+Convert.ToInt64(c["installed_bytes"])); count=checked(count+Convert.ToInt64(c["files"]));
            foreach(object item in (System.Collections.IEnumerable)c["downloads"]) {
                var a=(System.Collections.Generic.Dictionary<string,object>)item;
                string hash=(string)a["sha256"]; long bytes=Convert.ToInt64(a["bytes"]);
                if(downloads.ContainsKey(hash) && downloads[hash]!=bytes) throw new System.IO.IOException("Conflicting download sizes.");
                downloads[hash]=bytes;
            }
        }
        foreach(long bytes in downloads.Values) installed=checked(installed+bytes);
        count+=downloads.Count;
        return Check(path,installed,count,Convert.ToInt64(plan["bootstrap_bytes"]));
    }
}
