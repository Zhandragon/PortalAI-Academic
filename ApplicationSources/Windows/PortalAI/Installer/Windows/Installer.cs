using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Program {
    internal static readonly string Package = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    internal static JavaScriptSerializer Json() { return new JavaScriptSerializer { MaxJsonLength = Int32.MaxValue, RecursionLimit = 128 }; }
    internal static string Quote(string value) { return "\"" + value + "\""; }
    internal static string PrepareRuntime() {
        string root = Path.Combine(Package, ".PortalAI-installer-" + Guid.NewGuid().ToString("N"));
        if (Directory.Exists(root) || File.Exists(root)) throw new IOException("Installer work folder already exists.");
        Directory.CreateDirectory(root);
        using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("python-bootstrap.zip"))
        using (ZipArchive zip = new ZipArchive(resource, ZipArchiveMode.Read)) {
            foreach (ZipArchiveEntry entry in zip.Entries) {
                string path = Path.GetFullPath(Path.Combine(root, entry.FullName));
                if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe bundled runtime path.");
                if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                using (Stream input = entry.Open()) using (FileStream output = new FileStream(path, FileMode.CreateNew)) input.CopyTo(output);
            }
        }
        foreach (string name in new [] { "installer_core.py", "engine_cli.py", "installer_storage.py", "portable_update.py" }) {
            using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            using (FileStream output = new FileStream(Path.Combine(root, name), FileMode.CreateNew)) input.CopyTo(output);
        }
        return root;
    }
    internal static ProcessStartInfo Engine(string runtime, string argument) {
        string python = Path.Combine(runtime, "python.exe");
        if (!File.Exists(python)) throw new IOException("Bundled Python executable is missing.");
        return new ProcessStartInfo(python, "-B -I -X utf8 " + Quote(Path.Combine(runtime, "engine_cli.py")) + " " + argument) {
            WorkingDirectory = Package, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
    }
    [STAThread] public static int Main(string[] args) {
        try {
            if (args.Length == 1 && args[0] == "--verify-bootstrap") {
                string runtime = PrepareRuntime();
                using (Process process = Process.Start(Engine(runtime, "--selfcheck"))) {
                    Task<string> errors = process.StandardError.ReadToEndAsync();
                    string output = process.StandardOutput.ReadToEnd(); process.WaitForExit();
                    File.WriteAllText(Path.Combine(Package, "installer-selfcheck.json"), output, new UTF8Encoding(false));
                    if (process.ExitCode != 0) File.WriteAllText(Path.Combine(runtime, "error.txt"), errors.Result);
                    return process.ExitCode;
                }
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm(args.Length == 1 && args[0] == "--ui-smoke")); return 0;
        } catch (Exception error) { MessageBox.Show(error.Message, "PortalAI installer", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
    }
}

internal sealed class ComponentChoice {
    internal string Id, Label; internal bool Required;
    public override string ToString() { return Label + (Required ? " (required)" : ""); }
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
internal sealed class InstallerForm : Form {
    readonly CheckedListBox choices=new CheckedListBox(); readonly TextBox status=new TextBox();
    readonly PortalButton install=new PortalButton(),pause=new PortalButton(),close=new PortalButton(),theme=new PortalButton();
    readonly PortalProgress currentProgress=new PortalProgress(),overallProgress=new PortalProgress();
    readonly Label currentLabel=new Label(),currentBytes=new Label(),overallLabel=new Label(),title=new Label();
    readonly BackgroundWorker worker=new BackgroundWorker();
    readonly PortalButton upgrade=new PortalButton(); string upgradeTarget;
    string cancellation,lastStep; bool loading=true,dark=true; volatile bool pauseRequested;
    Color gold=Color.FromArgb(176,134,58); Point? drag;
    internal InstallerForm(bool smoke) {
        Text="PortalAI installer — version-aware r44"; Name="PortalAIInstaller";
        Size=new Size(900,830);MinimumSize=new Size(780,690);StartPosition=FormStartPosition.CenterScreen;
        FormBorderStyle=FormBorderStyle.None;Padding=new Padding(8);DoubleBuffered=true;
        Font=new Font("Segoe UI",9F);Icon=Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);
        var layout=new TableLayoutPanel { Dock=DockStyle.Fill,Padding=new Padding(12),RowCount=7,ColumnCount=1 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,52));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,88));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent,55));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,140));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,25));layout.RowStyles.Add(new RowStyle(SizeType.Percent,45));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,48));
        var header=new Panel { Dock=DockStyle.Fill };
        title.Text="PortalAI";title.Font=new Font("Georgia",20F,FontStyle.Bold);title.Dock=DockStyle.Fill;title.TextAlign=ContentAlignment.MiddleLeft;
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
        Label intro=new Label { Dock=DockStyle.Fill,AutoEllipsis=true,Text="PortalAI will be installed beside this installer:\r\n"+Program.Package+"\r\n\r\nChoose optional components below. Existing installation files will not be overwritten." };
        choices.Name="Components";choices.Dock=DockStyle.Fill;choices.CheckOnClick=true;choices.BorderStyle=BorderStyle.None;choices.IntegralHeight=false;
        choices.ItemCheck+=delegate(object sender,ItemCheckEventArgs e) { if(!loading && ((ComponentChoice)choices.Items[e.Index]).Required)e.NewValue=CheckState.Checked; };
        var progress=new TableLayoutPanel { Dock=DockStyle.Fill,RowCount=5,ColumnCount=1,Padding=new Padding(0,10,0,4) };
        foreach(int height in new[]{25,17,24,25,17})progress.RowStyles.Add(new RowStyle(SizeType.Absolute,height));
        currentLabel.Text="Ready to install";currentLabel.Name="CurrentComponent";currentLabel.AutoEllipsis=true;
        currentBytes.Name="DownloadBytes";currentBytes.Text="Download sizes and progress will appear here.";
        overallLabel.Name="OverallStatus";overallLabel.Text="Overall installation · 0%";
        currentProgress.Name="CurrentProgress";overallProgress.Name="OverallProgress";
        foreach(Control c in new Control[]{currentLabel,currentProgress,currentBytes,overallLabel,overallProgress}) { c.Dock=DockStyle.Fill;progress.Controls.Add(c); }
        status.Name="InstallationLog";status.Dock=DockStyle.Fill;status.Multiline=true;status.ReadOnly=true;status.ScrollBars=ScrollBars.Vertical;status.BorderStyle=BorderStyle.None;
        var buttons=new FlowLayoutPanel { Dock=DockStyle.Fill,FlowDirection=FlowDirection.RightToLeft,Padding=new Padding(0,9,0,0) };
        close.Text="Close";pause.Text="Pause";install.Text="Install here";pause.Enabled=false;
        upgrade.Text="Update existing";upgrade.Width=135;
        upgrade.Click+=delegate {
            using(var picker=new FolderBrowserDialog { Description="Choose the existing PortalAI application folder" }) {
                if(picker.ShowDialog(this)!=DialogResult.OK)return;
                upgradeTarget=picker.SelectedPath;install.Enabled=true;install.PerformClick();
            }
        };
        buttons.Controls.AddRange(new Control[]{close,pause,upgrade,install});
        foreach(Control c in new Control[]{header,intro,choices,progress,new Label { Text="Installation details",Dock=DockStyle.Fill },status,buttons})layout.Controls.Add(c);
        Controls.Add(layout);ApplyTheme();
        var release=Program.Json().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Program.Package,"release.json")));
        foreach(object row in (System.Collections.IEnumerable)release["components"]) {
            var data=(Dictionary<string,object>)row;
            var item=new ComponentChoice { Id=(string)data["id"],Label=Convert.ToString(data.ContainsKey("label") ? data["label"] : data["id"]),Required=data.ContainsKey("required") && Convert.ToBoolean(data["required"]) };
            choices.Items.Add(item,item.Required);
        }
        loading=false;Append("Ready. "+Convert.ToString(release["release"]));
        worker.WorkerReportsProgress=true;
        worker.ProgressChanged+=delegate(object sender,ProgressChangedEventArgs e) { var message=e.UserState as Dictionary<string,object>;if(message!=null)Progress(message);else Append(Convert.ToString(e.UserState)); };
        worker.DoWork+=RunInstall;
        worker.RunWorkerCompleted+=delegate(object sender,RunWorkerCompletedEventArgs e) {
            pause.Enabled=false;choices.Enabled=true;install.Enabled=true;upgrade.Enabled=true;upgradeTarget=null;currentProgress.Indeterminate=overallProgress.Indeterminate=false;
            if(e.Error!=null) { currentLabel.Text="Installation stopped";Append("Installation stopped: "+e.Error.Message); }
            else if(Convert.ToInt32(e.Result)!=0) { currentLabel.Text=Convert.ToInt32(e.Result)==2 ? "Paused — downloads retained" : "Installation did not complete";Append("See the details above. Downloaded files remain available for resume."); }
            else { currentLabel.Text="Installation verified";currentBytes.Text="All selected files are ready.";overallLabel.Text="Overall installation · 100%";currentProgress.Fraction=overallProgress.Fraction=1;Append("Installation verified. Open PortalAI normally. Updates preserve your existing accounts and settings.");install.Enabled=false; }
            currentProgress.Invalidate();overallProgress.Invalidate();
        };
        install.Click+=delegate {
            var selected=new List<string>();foreach(ComponentChoice item in choices.CheckedItems)selected.Add(item.Id);
            install.Enabled=false;upgrade.Enabled=false;choices.Enabled=false;pause.Enabled=false;cancellation=null;pauseRequested=false;lastStep=null;
            currentLabel.Text="Checking disk space and selected components…";currentBytes.Text="Preparing installation";overallLabel.Text="Overall installation · preparing";
            currentProgress.Fraction=overallProgress.Fraction=0;currentProgress.Indeterminate=overallProgress.Indeterminate=true;
            worker.RunWorkerAsync(selected.ToArray());
        };
        pause.Click+=delegate { RequestPause(); };close.Click+=delegate { Close(); };
        FormClosing+=delegate(object sender,FormClosingEventArgs e) { if(worker.IsBusy) { e.Cancel=true;RequestPause();Append("Waiting for the installer to stop safely before closing."); } };
        if(smoke) { var timer=new System.Windows.Forms.Timer { Interval=1200 };timer.Tick+=delegate { timer.Stop();Close(); };Shown+=delegate { timer.Start(); }; }
    }
    void ApplyTheme() {
        Color bg=ColorTranslator.FromHtml(dark ? "#111315" : "#EEE7DC"),panel=ColorTranslator.FromHtml(dark ? "#1C1E20" : "#F8F3EA"),text=ColorTranslator.FromHtml(dark ? "#F2ECE2" : "#202224");
        Color button=ColorTranslator.FromHtml(dark ? "#2A2D2F" : "#E6DCCB"),hover=ColorTranslator.FromHtml(dark ? "#363A3D" : "#D9CBB3"),accent=ColorTranslator.FromHtml(dark ? "#58AFC1" : "#3E91A2");
        gold=ColorTranslator.FromHtml(dark ? "#B0863A" : "#A87D32");
        PaintControls(this,bg,panel,text,button,hover);title.ForeColor=accent;
        theme.Text=dark ? "Light mode" : "Dark mode";
        currentProgress.Accent=accent;overallProgress.Accent=gold;currentProgress.BackColor=overallProgress.BackColor=panel;Invalidate(true);
    }
    void PaintControls(Control root,Color bg,Color panel,Color text,Color button,Color hover) {
        root.BackColor=root is TextBox || root is CheckedListBox ? panel : bg;root.ForeColor=text;
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
    static long Number(Dictionary<string,object> m,string key) { return m.ContainsKey(key) ? Convert.ToInt64(m[key]) : 0; }
    static string Bytes(long value) { return value>=1073741824L ? (value/1073741824.0).ToString("F2")+" GiB" : value>=1048576L ? (value/1048576.0).ToString("F1")+" MiB" : value>=1024L ? (value/1024.0).ToString("F1")+" KiB" : value+" B"; }
    internal void Progress(Dictionary<string,object> m) {
        string kind=m.ContainsKey("kind") ? Convert.ToString(m["kind"]) : "log",label=m.ContainsKey("message") ? Convert.ToString(m["message"]) : "";
        if(kind!="progress") { if(label.Length>0)Append(label);return; }
        string phase=Convert.ToString(m["phase"]),prefix=phase=="download" ? "Downloading / checking" : phase=="install" ? "Installing" : phase=="verify" ? "Verifying" : "Working";
        string step=prefix+" · "+label;currentLabel.Text=step;
        long done=Number(m,"done"),total=Number(m,"total"),all=Number(m,"overall_done"),allTotal=Number(m,"overall_total");
        currentProgress.Indeterminate=total<=0;currentProgress.Fraction=total>0 ? Math.Max(0,Math.Min(1,done/(double)total)) : 0;
        currentBytes.Text=total>0 ? String.Format("{0:F1}%   ·   {1} / {2}",currentProgress.Fraction*100,Bytes(done),Bytes(total)) : "This step is running; progress will update when verification finishes.";
        overallProgress.Indeterminate=false;overallProgress.Fraction=allTotal>0 ? Math.Max(0,Math.Min(.99,all/(double)allTotal)) : 0;
        overallLabel.Text=String.Format("Overall installation · {0:F0}%   (downloads, installation and verification)",Math.Floor(overallProgress.Fraction*100));
        currentProgress.Invalidate();overallProgress.Invalidate();
        if(lastStep!=step) { lastStep=step;Append(step); }
    }
    void Append(string text) { if(status.TextLength>60000)status.Text=status.Text.Substring(status.TextLength-40000);status.AppendText(text+Environment.NewLine); }
    void RequestPause() { pauseRequested=true;if(cancellation!=null)File.WriteAllText(cancellation,"pause");pause.Enabled=false;Append("Pause requested; waiting for the current safe checkpoint."); }
    void RunInstall(object sender,DoWorkEventArgs e) {
        if(upgradeTarget==null) { worker.ReportProgress(0,"Checking disk space for the selected components...");worker.ReportProgress(0,StoragePreflight.CheckSelection(Program.Package,(string[])e.Argument)); }
        if(pauseRequested) { e.Result=2;return; }
        worker.ReportProgress(0,"Preparing the bundled installer runtime...");string runtime=Program.PrepareRuntime();cancellation=Path.Combine(runtime,"cancel");
        if(pauseRequested)File.WriteAllText(cancellation,"pause");BeginInvoke((Action)delegate { pause.Enabled=true; });
        string request=Path.Combine(runtime,"request.json");
        if(upgradeTarget!=null) {
            File.WriteAllText(request,Program.Json().Serialize(new { package=Program.Package,destination=upgradeTarget,mode="plan" }),new UTF8Encoding(false));
            using(Process check=Process.Start(Program.Engine(runtime,Program.Quote(request)))) {
                Task<string> errors=check.StandardError.ReadToEndAsync();string line;string versionMessage=null;
                while((line=check.StandardOutput.ReadLine())!=null) {
                    var message=Program.Json().Deserialize<Dictionary<string,object>>(line);
                    worker.ReportProgress(0,message);
                    if(Convert.ToString(message["kind"])=="plan")versionMessage=Convert.ToString(message["message"]);
                }
                check.WaitForExit();if(check.ExitCode!=0 || versionMessage==null)throw new IOException("Version check failed. "+errors.Result);
                bool accepted=false;
                Invoke((Action)delegate { accepted=MessageBox.Show(this,versionMessage+"?\n\nClose PortalAI normally first. Your accounts, settings and unselected assets will be preserved. Verified recovery copies will be retained.","Review PortalAI update",MessageBoxButtons.OKCancel,MessageBoxIcon.Information)==DialogResult.OK; });
                if(!accepted) { e.Result=2;return; }
            }
        }
        File.WriteAllText(request,Program.Json().Serialize(new { package=Program.Package,destination=upgradeTarget ?? Program.Package,selected=(string[])e.Argument,cancel_file=cancellation,mode=upgradeTarget==null ? "install" : "upgrade" }),new UTF8Encoding(false));
        using(Process process=Process.Start(Program.Engine(runtime,Program.Quote(request)))) {
            Task<string> errors=process.StandardError.ReadToEndAsync();string line;
            using(var log=new StreamWriter(Path.Combine(runtime,"installer-log.jsonl"),false,new UTF8Encoding(false))) {
                while((line=process.StandardOutput.ReadLine())!=null) {
                    log.WriteLine(line);log.Flush();
                    try { var message=Program.Json().Deserialize<Dictionary<string,object>>(line);worker.ReportProgress(0,message); }
                    catch(ArgumentException) { worker.ReportProgress(0,line); }
                }
            }
            process.WaitForExit();if(errors.Result.Length>0)worker.ReportProgress(0,errors.Result);e.Result=process.ExitCode;
        }
    }
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
