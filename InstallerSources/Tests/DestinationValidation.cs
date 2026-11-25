using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Linq;
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
        using(var standalone=new InstallerForm(false))Check(Get<TextBox>(standalone,"destinationBox").Text==Path.GetPathRoot(Program.Package),"Direct Windows installer also defaults to its drive root");
        using(var host=new UserControl{Size=new Size(1060,960)})using(var form=new InstallerForm(false,@"E:\")){
            form.TopLevel=false;form.Dock=DockStyle.Fill;host.Controls.Add(form);host.CreateControl();form.Show();Application.DoEvents();
            form.GetType().GetMethod("CloseSurvey",F).Invoke(form,null);
            var box=Get<TextBox>(form,"destinationBox");var preview=Get<Label>(form,"destinationPreview");
            Check(box.Text==@"E:\"&&preview.Text.Contains(@"E:\PortalAI Windows"),"Bundle destination is displayed correctly");
            box.Text=@"E:\My AI";Check(preview.Text.Contains(@"E:\My AI\PortalAI Windows"),"Preview follows edits");
            Get<PortalButton>(form,"driveRoot").PerformClick();Check(box.Text==@"E:\","Drive root button follows selected drive");
            Check(Get<PortalButton>(form,"browseDestination").Enabled,"Browse is available before installation");
            var choices=Get<CheckedListBox>(form,"choices");
            var copies=choices.Items.Cast<ComponentChoice>().Where(c=>c.Id.StartsWith("copy:")).ToArray();
            int expectedCopies=Get<string>(form,"primaryEdition")=="Full" ? 8 : 4;
            Check(copies.Length==expectedCopies,"Current per-OS bundle choices are displayed without old native copies");
            Check(copies.Any(c=>c.Id.EndsWith("-universal")),"All-three-OS bundle copy is available");
            Check(choices.Items.Cast<ComponentChoice>().Any(c=>c.Id=="whisper-turbo-model"),"Complete model catalog is shown");
            Get<PortalButton>(form,"allComponentsButton").PerformClick();
            Check(copies.All(c=>choices.CheckedItems.Contains(c)),"All components includes current installer bundle copies");
            Check(choices.Items.Cast<ComponentChoice>().Where(c=>c.Review!=null).All(c=>choices.CheckedItems.Contains(c)),"All components includes every optional model group");
            Get<PortalButton>(form,"expressButton").PerformClick();
            Check(!choices.CheckedItems.Cast<ComponentChoice>().Any(c=>c.Id=="whisper-turbo-model"||c.Id.StartsWith("utility:")),"Express stays lightweight and utilities remain optional");
            Check(Get<TextBox>(form,"huggingfaceToken").UseSystemPasswordChar&&Get<TextBox>(form,"huggingfaceToken").Text=="","Recipient model credential starts empty and masked");
            Shot(form,"destination-dark.png");host.Size=new Size(850,790);Shot(form,"destination-small.png");
            typeof(InstallerForm).GetField("dark",F).SetValue(form,false);form.GetType().GetMethod("ApplyTheme",F).Invoke(form,null);Shot(form,"destination-light.png");
            Check(!Get<System.ComponentModel.BackgroundWorker>(form,"worker").IsBusy,"Choosing a folder does not start installation");
        }
        return 0;
    }catch(Exception e){Console.WriteLine(e);return 1;}}
}
