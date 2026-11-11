using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

internal sealed class InstallInterest {
    internal string Id, Label, Description;
    internal string[] Light, Full;
    internal InstallInterest(string id,string label,string description,string light,string full="") {
        Id=id;Label=label;Description=description;Light=light.Split(new[]{' '},StringSplitOptions.RemoveEmptyEntries);Full=full.Split(new[]{' '},StringSplitOptions.RemoveEmptyEntries);
    }
    public override string ToString(){return Label;}
}
internal static class InstallBundles {
    internal static readonly InstallInterest[] Interests={
        new InstallInterest("chat","Everyday chat & standard models","A small chat model; Full adds a larger chat and vision choice.","text-small","text-4b vision-4b"),
        new InstallInterest("coding","Coding & software development","General coding assistance; Full adds the optional specialist where available.","text-small","text-4b coding-swift-27b text-27b-standard"),
        new InstallInterest("documents","Documents, images & data analysis","Vision models for images, plus the shared document and data tools.","text-small vision-2b","text-4b vision-4b"),
        new InstallInterest("bio","Bioinformatics & protein design","Shared genomics tools and ProteinMPNN; Full adds the optional plasmid annotation databases.","text-small protein-runtime","text-4b science-plannotate-databases"),
        new InstallInterest("physics","Physics & physical simulations","Shared scientific tools and interactive physics examples.","text-small","text-4b"),
        new InstallInterest("electrical","Electrical engineering & circuits","Shared science tools and the circuit-design runtime.","text-small kicad-native","text-4b"),
        new InstallInterest("mechanical","Mechanical engineering, CAD & 3D printing","Shared CAD and mesh tools; Full adds the optional slicer.","text-small","text-4b science-print-slicer"),
        new InstallInterest("chemistry","Chemistry & molecular simulation","Shared chemistry and simulation tools; no separate large model collection is needed.","text-small","text-4b"),
        new InstallInterest("math","Math, statistics & signal processing","Shared numerical and signal-processing tools.","text-small","text-4b"),
        new InstallInterest("music","Music generation","A smaller CPU music workflow; Full adds ACE-Step and supporting music models. Separate model terms apply.","text-small musicgen-cpu-models","ace-step-models ace-language-model-optional ace-step-extra-models-optional"),
        new InstallInterest("media","Media editing & audio cleanup","Audio separation and shared media tools; Full adds image/video editing and segmentation models.","text-small demucs-model","instruction-edit-models-optional vace-small-models-optional sam2-models music-understanding-models-optional"),
        new InstallInterest("images","Image generation","The smaller SD1.5 workflow; Full adds the Flux model collection and its shared supporting files.","text-small sd15-models","flux-model-subset-optional"),
        new InstallInterest("video","Video generation & animation","The dedicated Wan subset; even Lightweight can be a large download. Full adds video editing and lip-sync models.","text-small wan-model-subset-optional","vace-small-models-optional musetalk-models"),
        new InstallInterest("voice","Handsfree voice & dictation","Speech recognition and CPU speech; Full adds richer Qwen speech models.","text-small whisper-base-model piper-voice","qwen-tts-models"),
        new InstallInterest("alternate","Alternate / unrestricted-model workflows","Full-edition text bundles include alternate and standard variants. This does not remove publisher license restrictions or change the app's active model policy.","text-small","text-4b vision-4b")
    };
    internal static HashSet<string> Recommend(IEnumerable<ComponentChoice> inventory,IEnumerable<string> interests,bool full,string edition) {
        var all=inventory.ToDictionary(x=>x.Id);var selected=new HashSet<string>(all.Values.Where(x=>x.Required).Select(x=>x.Id));
        if(all.ContainsKey("primary:"+edition))selected.Add("primary:"+edition);
        foreach(var interest in Interests)if(interests.Contains(interest.Id)&&!(edition=="Academic"&&interest.Id=="alternate"))
            foreach(string id in full?interest.Light.Concat(interest.Full):interest.Light)if(all.ContainsKey(id))selected.Add(id);
        return Expand(all.Values,selected);
    }
    internal static HashSet<string> Expand(IEnumerable<ComponentChoice> inventory,IEnumerable<string> selected) {
        var all=inventory.ToDictionary(x=>x.Id);var result=new HashSet<string>(selected);bool changed;
        do{changed=false;foreach(var c in all.Values)if(result.Contains(c.Id)||c.Required){if(result.Add(c.Id))changed=true;foreach(var dep in c.Dependencies){if(!all.ContainsKey(dep))throw new InvalidOperationException("Missing component dependency: "+dep);if(result.Add(dep))changed=true;}}}while(changed);
        return result;
    }
}

internal sealed partial class InstallerForm {
    readonly PortalButton surveyButton=new PortalButton(),expressButton=new PortalButton(),manualButton=new PortalButton();
    readonly Label setupMode=new Label{AutoSize=true,Padding=new Padding(6,8,0,0)};
    Panel surveyOverlay; int surveyPage; bool fullBundle;
    HashSet<string> surveyInterests=new HashSet<string>{"chat"};
    HashSet<string> surveySelection;
    Control mainLayout;
    FlowLayoutPanel BuildSetupBar() {
        var bar=new FlowLayoutPanel{Dock=DockStyle.Bottom,Height=42,WrapContents=false};
        surveyButton.Text="Help me choose";surveyButton.Width=140;surveyButton.Click+=delegate{OpenSurvey(1);};
        expressButton.Text="Express";expressButton.Click+=delegate{ApplyBundle(InstallBundles.Recommend(Inventory(),new[]{"chat"},false,primaryEdition),"Express Â· Lightweight chat");};
        manualButton.Text="Custom";manualButton.Click+=delegate{setupMode.Text="âœ“ Custom Â· choose components below";choices.Focus();};
        bar.Controls.AddRange(new Control[]{surveyButton,expressButton,manualButton,setupMode});setupMode.Text="Choose a setup path";return bar;
    }
    IEnumerable<ComponentChoice> Inventory(){return choices.Items.Cast<ComponentChoice>();}
    void ApplyBundle(HashSet<string> selected,string mode) {
        if(worker.IsBusy)return;
        loading=true;try{for(int i=0;i<choices.Items.Count;i++)choices.SetItemChecked(i,selected.Contains(((ComponentChoice)choices.Items[i]).Id));}finally{loading=false;}
        setupMode.Text="âœ“ "+mode;UpdateSelectionSize();Append("Selection applied. Review or change the components below, then choose Install here when ready. No downloads have started.");
    }
    void CloseSurvey(){if(surveyOverlay!=null){Controls.Remove(surveyOverlay);surveyOverlay.Dispose();surveyOverlay=null;}if(mainLayout!=null){mainLayout.Enabled=true;mainLayout.Visible=true;}}
    PortalButton SurveyButton(string text,Action action,int width=135){var b=new PortalButton{Text=text,Width=width,Height=36};b.Click+=delegate{action();};return b;}
    Label SurveyText(string text,int size=11){return new Label{Text=text,AutoSize=true,MaximumSize=new Size(700,0),Font=new Font("Segoe UI",size),Margin=new Padding(0,8,0,8)};}
    void OpenSurvey(int page) {
        if(worker.IsBusy)return;
        CloseSurvey();surveyPage=page;mainLayout.Enabled=false;mainLayout.Visible=false;
        surveyOverlay=new Panel{Dock=DockStyle.Fill,Padding=new Padding(30)};Controls.Add(surveyOverlay);surveyOverlay.BringToFront();
        var card=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=3,Padding=new Padding(18)};
        card.RowStyles.Add(new RowStyle(SizeType.AutoSize));card.RowStyles.Add(new RowStyle(SizeType.Percent,100));card.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var heading=SurveyText(page==0?"Choose how to set up PortalAI":page==1?"1 of 2 Â· What will you use PortalAI for?":"2 of 2 Â· Review your bundle",18);card.Controls.Add(heading);
        var body=new FlowLayoutPanel{Dock=DockStyle.Fill,AutoScroll=true,FlowDirection=FlowDirection.TopDown,WrapContents=false};card.Controls.Add(body);
        var actions=new FlowLayoutPanel{Dock=DockStyle.Fill,AutoSize=true,WrapContents=true,Padding=new Padding(0,12,0,0)};card.Controls.Add(actions);surveyOverlay.Controls.Add(card);
        if(page==0) {
            body.Controls.Add(SurveyText("A short optional survey groups downloads by what you want to do. You can review every recommendation before installing."));
            body.Controls.Add(SurveyText("Express starts with a lightweight chat bundle. Custom keeps the component list under your control. You can retake the survey with Help me choose."));
            actions.Controls.Add(SurveyButton("Take survey",()=>OpenSurvey(1)));
            actions.Controls.Add(SurveyButton("Express",()=>{CloseSurvey();expressButton.PerformClick();}));
            actions.Controls.Add(SurveyButton("Skip Â· Custom",()=>{CloseSurvey();manualButton.PerformClick();}));
        } else if(page==1) {
            body.Controls.Add(SurveyText("Select any interests. Shared scientific tools are already part of the base installation; several interests may use the same files."));
            var uses=new CheckedListBox{Name="SurveyInterests",CheckOnClick=true,Width=700,Height=320,IntegralHeight=false,BorderStyle=BorderStyle.None};
            foreach(var interest in InstallBundles.Interests)if(primaryEdition!="Academic"||interest.Id!="alternate")uses.Items.Add(interest,surveyInterests.Contains(interest.Id));
            body.Controls.Add(uses);var explanation=SurveyText("Select a line to see what it includes.");body.Controls.Add(explanation);
            uses.SelectedIndexChanged+=delegate{var item=uses.SelectedItem as InstallInterest;if(item!=null)explanation.Text=item.Description;};
            var size=new FlowLayoutPanel{AutoSize=true,WrapContents=false};var light=new RadioButton{Text="Lightweight",AutoSize=true,Checked=!fullBundle};var full=new RadioButton{Text="Full",AutoSize=true,Checked=fullBundle};size.Controls.Add(light);size.Controls.Add(full);body.Controls.Add(size);
            body.Controls.Add(SurveyText("Lightweight = fewer/smaller model choices for your interests. Full = broader coverage for those interests, not every optional package. Both include the required shared runtimes. Download size does not guarantee RAM or GPU compatibility.",10));
            actions.Controls.Add(SurveyButton("Skip survey",CloseSurvey));
            actions.Controls.Add(SurveyButton("Review bundle",()=>{surveyInterests=new HashSet<string>(uses.CheckedItems.Cast<InstallInterest>().Select(x=>x.Id));fullBundle=full.Checked;surveySelection=InstallBundles.Recommend(Inventory(),surveyInterests,fullBundle,primaryEdition);OpenSurvey(2);}));
            body.SizeChanged+=delegate{uses.Width=Math.Max(240,body.ClientSize.Width-24);};
        } else {
            body.Controls.Add(SurveyText((fullBundle?"Full":"Lightweight")+" Â· "+surveyInterests.Count+" interests Â· "+surveySelection.Count+" components (including required files)"));
            body.Controls.Add(SurveyText(SelectionEstimate(surveySelection),10));
            var review=new TextBox{Name="BundleReview",ReadOnly=true,Multiline=true,ScrollBars=ScrollBars.Vertical,Width=700,Height=310,Text=String.Join("\r\n",Inventory().Where(x=>surveySelection.Contains(x.Id)).Select(x=>"â€¢ "+x.Label+(x.Required?" [required]":"")+(x.Review!=null?" [license review]":"")))};body.Controls.Add(review);
            body.Controls.Add(SurveyText("Apply only selects these components. You can edit the list next. Install here performs the separate model-license review and disk-space check before downloading. No model policy is changed by this survey.",10));
            if(primaryEdition=="Full"&&surveySelection.Overlaps(new[]{"text-small","text-4b","vision-2b","vision-4b"}))body.Controls.Add(SurveyText("Full-edition chat/vision downloads contain standard and alternate variants together. Selecting standard-model interests does not exclude alternate files from these existing bundles.",10));
            actions.Controls.Add(SurveyButton("â€¹ Back",()=>OpenSurvey(1)));actions.Controls.Add(SurveyButton("Skip survey",CloseSurvey));actions.Controls.Add(SurveyButton("Apply & review",()=>{CloseSurvey();ApplyBundle(surveySelection,(fullBundle?"Full":"Lightweight")+" survey bundle");},160));
            body.SizeChanged+=delegate{review.Width=Math.Max(240,body.ClientSize.Width-24);};
        }
        body.SizeChanged+=delegate{foreach(Control item in body.Controls)if(item is Label)item.MaximumSize=new Size(Math.Max(220,body.ClientSize.Width-24),0);};
        ApplyTheme();heading.ForeColor=ColorTranslator.FromHtml(dark?"#58AFC1":"#24798B");surveyOverlay.Focus();
    }
    protected override bool ProcessCmdKey(ref Message m,Keys key){if(surveyOverlay!=null&&key==Keys.Escape){CloseSurvey();return true;}return base.ProcessCmdKey(ref m,key);}
}
