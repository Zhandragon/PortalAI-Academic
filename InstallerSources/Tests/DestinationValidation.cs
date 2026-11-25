using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
class DestinationValidation {
    static BindingFlags F=BindingFlags.Instance|BindingFlags.NonPublic;
    static T Get<T>(object o,string name){return (T)o.GetType().GetField(name,F).GetValue(o);}
    static void Check(bool yes,string text){if(!yes)throw new Exception(text);Console.WriteLine("PASS: "+text);}
    static void Shot(Form form,string name){Application.DoEvents();using(var b=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(b,new Rectangle(Point.Empty,form.Size));b.Save(Path.Combine(Program.Package,name));}}
    [STAThread]static int Main(){try{
        Application.EnableVisualStyles();
        Check(InstallDestination.Normalize(@"E:\")==@"E:\","Drive root accepted");
        Check(InstallDestination.Normalize(@"E:\My AI")==@"E:\My AI","Folder with spaces accepted");
        foreach(string bad in new[]{"","relative","E:"}){bool rejected=false;try{InstallDestination.Normalize(bad);}catch(ArgumentException){rejected=true;}Check(rejected,"Relative/empty input rejected");}
        using(var host=new UserControl{Size=new Size(1060,960)})using(var form=new InstallerForm(false,@"E:\")){
            form.TopLevel=false;form.Dock=DockStyle.Fill;host.Controls.Add(form);host.CreateControl();form.Show();Application.DoEvents();
            form.GetType().GetMethod("CloseSurvey",F).Invoke(form,null);
            var box=Get<TextBox>(form,"destinationBox");var preview=Get<Label>(form,"destinationPreview");
            Check(box.Text==@"E:\"&&preview.Text.Contains(@"E:\PortalAI Windows"),"Bundle destination is displayed correctly");
            box.Text=@"E:\My AI";Check(preview.Text.Contains(@"E:\My AI\PortalAI Windows"),"Preview follows edits");
            Get<PortalButton>(form,"driveRoot").PerformClick();Check(box.Text==@"E:\","Drive root button follows selected drive");
            Check(Get<PortalButton>(form,"browseDestination").Enabled,"Browse is available before installation");
            Shot(form,"destination-dark.png");host.Size=new Size(850,790);Shot(form,"destination-small.png");
            typeof(InstallerForm).GetField("dark",F).SetValue(form,false);form.GetType().GetMethod("ApplyTheme",F).Invoke(form,null);Shot(form,"destination-light.png");
            Check(!Get<System.ComponentModel.BackgroundWorker>(form,"worker").IsBusy,"Choosing a folder does not start installation");
        }
        return 0;
    }catch(Exception e){Console.WriteLine(e);return 1;}}
}
