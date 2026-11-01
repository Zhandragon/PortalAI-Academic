// Read-only, bounded Windows UI Automation helper. No input or value patterns.
using System;
using System.Collections.Generic;
using System.Text;
using System.Windows.Automation;
using System.Web.Script.Serialization;

class AccessibilitySnapshot {
    [STAThread]
    static int Main(string[] args) {
        try {
            long handle;
            if (args.Length != 1 || !long.TryParse(args[0], out handle)) return 2;
            var target = AutomationElement.FromHandle(new IntPtr(handle));
            if (target == null) return 3;
            var queue = new Queue<KeyValuePair<AutomationElement,int>>();
            queue.Enqueue(new KeyValuePair<AutomationElement,int>(target, 0));
            var rows = new List<object>(); int visited = 0;
            var walker = TreeWalker.ControlViewWalker;
            while (queue.Count > 0 && visited < 256 && rows.Count < 80) {
                var entry = queue.Dequeue(); visited++;
                try {
                    var element = entry.Key; var current = element.Current;
                    if (current.IsPassword) continue;
                    var rect = current.BoundingRectangle;
                    if (!current.IsOffscreen && rect.Width > 0 && rect.Height > 0) {
                        rows.Add(new { id=string.Join("_",element.GetRuntimeId()),
                            name=Bound(current.Name), role=current.ControlType.ProgrammaticName,
                            automation_id=Bound(current.AutomationId), enabled=current.IsEnabled,
                            rect=new double[] {rect.X,rect.Y,rect.Width,rect.Height} });
                    }
                    if (entry.Value < 12) {
                        var child = walker.GetFirstChild(element); int siblings = 0;
                        while (child != null && siblings++ < 80 && queue.Count < 256) {
                            queue.Enqueue(new KeyValuePair<AutomationElement,int>(child,entry.Value+1));
                            child=walker.GetNextSibling(child);
                        }
                    }
                } catch (ElementNotAvailableException) { }
            }
            Console.OutputEncoding = new UTF8Encoding(false);
            Console.Write(new JavaScriptSerializer().Serialize(new {elements=rows,bounded=true,visited=visited}));
            return 0;
        } catch (Exception) { return 4; }
    }
    static string Bound(string value) { return string.IsNullOrEmpty(value) ? "" : value.Substring(0,Math.Min(160,value.Length)); }
}
