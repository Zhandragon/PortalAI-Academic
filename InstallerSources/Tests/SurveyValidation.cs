using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using System.Windows.Forms;
class SurveyValidation {
 static BindingFlags F=BindingFlags.Instance|BindingFlags.NonPublic;
 static object Get(object o,string n){return o.GetType().GetField(n,F).GetValue(o);}
 static void Call(object o,string n,params object[] a){o.GetType().GetMethod(n,F).Invoke(o,a);Application.DoEvents();}
 static void Check(bool value,string note){if(!value)throw new Exception(note);Console.WriteLine("PASS: "+note);}
 static IEnumerable<T> All<T>(Control root)where T:Control {if(root is T)yield return (T)root;foreach(Control c in root.Controls)foreach(var d in All<T>(c))yield return d;}
 static void Click(Control root,string title){All<PortalButton>(root).Single(b=>b.Text==title).PerformClick();Application.DoEvents();}
 static HashSet<string> Chosen(InstallerForm f){return new HashSet<string>(((CheckedListBox)Get(f,"choices")).CheckedItems.Cast<ComponentChoice>().Select(c=>c.Id));}
 static void Shot(Form f,string name){Application.DoEvents();using(var b=new Bitmap(f.Width,f.Height)){f.DrawToBitmap(b,new Rectangle(Point.Empty,f.Size));b.Save(Path.Combine(Program.Package,name+".png"));}}
 [STAThread]static int Main(){try{Application.EnableVisualStyles();
  using(var host=new UserControl{Size=new Size(1060,960)})using(var f=new InstallerForm(false)){f.TopLevel=false;f.Dock=DockStyle.Fill;host.Controls.Add(f);host.CreateControl();f.Show();Application.DoEvents();
   Call(f,"CloseSurvey");var original=Chosen(f);Call(f,"OpenSurvey",1);Shot(f,"survey-interests");Click((Control)Get(f,"surveyOverlay"),"Skip survey");Check(original.SetEquals(Chosen(f)),"Skipping the survey preserves component selections");
   Call(f,"OpenSurvey",1);Click((Control)Get(f,"surveyOverlay"),"Review bundle");Shot(f,"survey-review");Check(original.SetEquals(Chosen(f)),"Review does not apply selections or install");
   Click((Control)Get(f,"surveyOverlay"),"Apply & review");var light=Chosen(f);Check(light.Contains("text-small")&&!light.Contains("text-4b")&&!light.Contains("comfy-models-optional"),"Lightweight chat selects a small model, not the full model collection");
   var inventory=((CheckedListBox)Get(f,"choices")).Items.Cast<ComponentChoice>().ToList();var all=InstallBundles.Interests.Select(x=>x.Id).ToArray();
   var full=InstallBundles.Recommend(inventory,all,true,"Full");var small=InstallBundles.Recommend(inventory,all,false,"Full");
   Check(small.IsSubsetOf(full)&&full.Contains("text-4b"),"Full extends Lightweight for the same interests");
   Check(full.Contains("shared-image-video-models"),"Video/image model dependencies are included for review");
   Check(inventory.Where(x=>x.Required).All(x=>full.Contains(x.Id)),"Required shared runtimes remain included");
   Check(!full.Any(x=>x.StartsWith("utility:")||x.StartsWith("copy:")||x.StartsWith("app:")),"Survey does not select unrelated installers or utilities");
   var academic=InstallBundles.Recommend(inventory,new[]{"alternate"},true,"Academic");Check(!academic.Contains("text-small"),"Academic ignores alternate-model interest");
   bool rejected=false;try{InstallBundles.Expand(new[]{new ComponentChoice{Id="broken",Dependencies=new[]{"missing"}}},new[]{"broken"});}catch(InvalidOperationException){rejected=true;}Check(rejected,"Missing dependencies stop recommendation rather than silently disappearing");
   typeof(InstallerForm).GetField("fullBundle",F).SetValue(f,true);typeof(InstallerForm).GetField("surveyInterests",F).SetValue(f,new HashSet<string>{"voice","images","bio"});Call(f,"OpenSurvey",1);Click((Control)Get(f,"surveyOverlay"),"Review bundle");host.Size=new Size(850,790);Shot(f,"survey-review-small-dark");Call(f,"CloseSurvey");typeof(InstallerForm).GetField("dark",F).SetValue(f,false);Call(f,"OpenSurvey",1);Shot(f,"survey-small-light");
   Check(!((System.ComponentModel.BackgroundWorker)Get(f,"worker")).IsBusy,"Survey never starts the installer worker");
  }return 0;}catch(Exception e){Console.WriteLine(e);return 1;}}
}
