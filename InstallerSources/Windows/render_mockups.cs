// Render the real installer forms with sample input, without displaying windows
// or starting downloads. Used only for product review, never release execution.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
internal static class InstallerMockups {
    static void PrepareChildren(Control parent) {
        foreach(Control child in parent.Controls) {
            var handle=child.Handle;child.CreateControl();child.PerformLayout();
            var combo=child as ComboBox;
            if(combo!=null) { var selected=combo.SelectedIndex;combo.SelectedIndex=-1;combo.SelectedIndex=selected; }
            PrepareChildren(child);
        }
    }
    static void Save(Form form,string file) {
        using(form) { var handle=form.Handle;
            // Keep the native top-level window hidden, but let WinForms lay out
            // and paint its child controls for an offscreen artifact.
            typeof(Control).GetMethod("SetState",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).Invoke(form,new object[]{2,true});
            form.CreateControl();form.PerformLayout();PrepareChildren(form);
            using(var bitmap=new Bitmap(form.Width,form.Height)) { form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(file,System.Drawing.Imaging.ImageFormat.Png); }
        }
    }
    [STAThread] public static int Main(string[] args) {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        string output=args[0];Directory.CreateDirectory(output);
        var release=Program.Json().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Program.Package,"release.json")));
        Save(new InstallerForm(false),Path.Combine(output,"01-installer-model-checkboxes.png"));
        var selected=new List<ComponentChoice>();
        foreach(object row in (System.Collections.IEnumerable)release["components"]) {
            var d=(Dictionary<string,object>)row;
            if(!d.ContainsKey("model_choice"))continue;
            if(Convert.ToString(d["id"])!="musicgen-cpu-models"&&Convert.ToString(d["id"])!="text-small")continue;
            selected.Insert(0,new ComponentChoice { Id=Convert.ToString(d["id"]),Label=Convert.ToString(d["label"]),Review=(Dictionary<string,object>)d["model_choice"] });
        }
        Save(new ModelReviewForm(selected),Path.Combine(output,"02-license-and-source-review.png"));
        Save(new CustomModelForm(false),Path.Combine(output,"03-custom-model-inputs.png"));
        var example=new Dictionary<string,object> { {"label","Example compatible chat model"},{"url","https://publisher.example/models/example-qwen3.gguf"},{"sha256",new string('a',64)},{"bytes",1834426016L},{"license_url","https://publisher.example/models/LICENSE"},{"variant","standard"} };
        Save(new CustomModelForm(false,example),Path.Combine(output,"04-custom-model-filled-example.png"));
        Save(new CustomModelForm(true),Path.Combine(output,"05-academic-model-inputs.png"));
        return 0;
    }
}
