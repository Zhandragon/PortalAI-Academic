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
        foreach (string name in new [] { "installer_core.py", "engine_cli.py", "installer_storage.py", "academic_policy.py" }) {
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
internal sealed class InstallerForm : Form {
    readonly CheckedListBox choices = new CheckedListBox();
    readonly TextBox status = new TextBox();
    readonly Button install = new Button(), pause = new Button(), close = new Button();
    readonly BackgroundWorker worker = new BackgroundWorker();
    string cancellation; bool loading = true; volatile bool pauseRequested;
    internal InstallerForm(bool smoke) {
        Text = "PortalAI Academic installer — 2026.10.20 r1"; Size = new Size(850, 700); MinimumSize = new Size(750, 620); StartPosition = FormStartPosition.CenterScreen;
        TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), RowCount = 5, ColumnCount = 1 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 100)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 60));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 35)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 40)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
        Label intro = new Label { Dock = DockStyle.Fill, AutoEllipsis = true, Text = "PortalAI Academic (standard/censored only) will be installed beside this installer:\r\n" + Program.Package + "\r\n\r\nExisting installation files will not be overwritten. Internet is needed for selected downloads." };
        choices.Dock = DockStyle.Fill; choices.CheckOnClick = true;
        choices.ItemCheck += delegate(object sender, ItemCheckEventArgs e) { if (!loading && ((ComponentChoice)choices.Items[e.Index]).Required) e.NewValue = CheckState.Checked; };
        status.Dock = DockStyle.Fill; status.Multiline = true; status.ReadOnly = true; status.ScrollBars = ScrollBars.Vertical;
        FlowLayoutPanel buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
        close.Text = "Close"; pause.Text = "Pause"; install.Text = "Install here"; pause.Enabled = false;
        buttons.Controls.AddRange(new Control[] { close, pause, install });
        layout.Controls.Add(intro); layout.Controls.Add(choices); layout.Controls.Add(new Label { Text = "Progress", Dock = DockStyle.Fill, TextAlign = ContentAlignment.BottomLeft }); layout.Controls.Add(status); layout.Controls.Add(buttons); Controls.Add(layout);
        Dictionary<string, object> release = Program.Json().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(Program.Package, "release.json")));
        foreach (object row in (System.Collections.IEnumerable)release["components"]) {
            Dictionary<string, object> data = (Dictionary<string, object>)row;
            ComponentChoice item = new ComponentChoice { Id = (string)data["id"], Label = Convert.ToString(data.ContainsKey("label") ? data["label"] : data["id"]), Required = data.ContainsKey("required") && Convert.ToBoolean(data["required"]) };
            choices.Items.Add(item, item.Required);
        }
        loading = false; Append("Ready. " + Convert.ToString(release["release"]));
        worker.WorkerReportsProgress = true;
        worker.ProgressChanged += delegate(object sender, ProgressChangedEventArgs e) { Append(Convert.ToString(e.UserState)); };
        worker.DoWork += RunInstall;
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e) {
            pause.Enabled = false; choices.Enabled = true; install.Enabled = true;
            if (e.Error != null) Append("Installation stopped: " + e.Error.Message);
            else if (Convert.ToInt32(e.Result) != 0) Append("Installation did not complete. See the message above; downloaded files remain available for resume.");
            else { Append("Installation verified. Open PortalAI.exe beside this installer to create your account."); install.Enabled = false; }
        };
        install.Click += delegate {
            List<string> selected = new List<string>(); foreach (ComponentChoice item in choices.CheckedItems) selected.Add(item.Id);
            install.Enabled = false; choices.Enabled = false; pause.Enabled = false; cancellation = null; pauseRequested = false;
            worker.RunWorkerAsync(selected.ToArray());
        };
        pause.Click += delegate { RequestPause(); };
        close.Click += delegate { Close(); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (worker.IsBusy) { e.Cancel = true; RequestPause(); Append("Waiting for the installer to stop safely before closing."); } };
        if (smoke) { System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 1200 }; timer.Tick += delegate { timer.Stop(); Close(); }; Shown += delegate { timer.Start(); }; }
    }
    void Append(string text) { status.AppendText(text + Environment.NewLine); }
    void RequestPause() { pauseRequested = true; if (cancellation != null) File.WriteAllText(cancellation, "pause"); pause.Enabled = false; Append("Pause requested; waiting for the current safe checkpoint."); }
    void RunInstall(object sender, DoWorkEventArgs e) {
        worker.ReportProgress(0, "Checking disk space for the selected components...");
        worker.ReportProgress(0, StoragePreflight.CheckSelection(Program.Package, (string[])e.Argument));
        if (pauseRequested) { e.Result = 2; return; }
        worker.ReportProgress(0, "Preparing the bundled installer runtime...");
        string runtime = Program.PrepareRuntime(); cancellation = Path.Combine(runtime, "cancel");
        if (pauseRequested) File.WriteAllText(cancellation, "pause");
        BeginInvoke((Action)delegate { pause.Enabled = true; });
        string request = Path.Combine(runtime, "request.json");
        File.WriteAllText(request, Program.Json().Serialize(new { package = Program.Package, destination = Program.Package, selected = (string[])e.Argument, cancel_file = cancellation }), new UTF8Encoding(false));
        using (Process process = Process.Start(Program.Engine(runtime, Program.Quote(request)))) {
            Task<string> errors = process.StandardError.ReadToEndAsync();
            string line; using (StreamWriter log = new StreamWriter(Path.Combine(runtime, "installer-log.jsonl"), false, new UTF8Encoding(false))) {
                while ((line = process.StandardOutput.ReadLine()) != null) {
                    log.WriteLine(line); log.Flush();
                    try { Dictionary<string, object> message = Program.Json().Deserialize<Dictionary<string, object>>(line); if (message.ContainsKey("message")) worker.ReportProgress(0, message["message"]); }
                    catch (ArgumentException) { worker.ReportProgress(0, line); }
                }
            }
            process.WaitForExit(); if (errors.Result.Length > 0) worker.ReportProgress(0, errors.Result); e.Result = process.ExitCode;
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
