"""Geometry regression checks without creating native windows."""
from collections import deque
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from activity_monitor import ActivityCharts
from ui_extensions import ResponsiveFlow, bind_responsive_wrap


class ResizeTests(unittest.TestCase):
    def test_chart_trace_tracks_both_canvas_dimensions(self):
        canvas=Mock(); canvas.winfo_width.return_value=800; canvas.winfo_height.return_value=200
        charts=SimpleNamespace(palette={}, canvases={'cpu':canvas}, samples=deque([
            {'at':0,'cpu':0}, {'at':300,'cpu':100}]))
        ActivityCharts.redraw(charts)
        self.assertEqual(canvas.create_line.call_args.args, (2,197,798,3))
        canvas.winfo_width.return_value=200; canvas.winfo_height.return_value=62
        ActivityCharts.redraw(charts)
        self.assertEqual(canvas.create_line.call_args.args, (2,59,198,3))

    def test_chart_cards_reflow_after_shrink_and_expand(self):
        charts=SimpleNamespace(_columns=None, cells=[Mock() for _ in range(4)], window_label=Mock(),
            labels={},canvases={},columnconfigure=Mock(),rowconfigure=Mock())
        for width,cols in ((1100,4),(700,2),(390,1),(1000,4)):
            ActivityCharts.reflow(charts,SimpleNamespace(widget=charts,width=width))
            for index,cell in enumerate(charts.cells):
                self.assertEqual(cell.grid.call_args.kwargs['row'],index//cols)
                self.assertEqual(cell.grid.call_args.kwargs['column'],index%cols)

    def test_flow_oversized_child_never_exceeds_available_width(self):
        child=Mock();child.winfo_reqwidth.return_value=866;child.winfo_reqheight.return_value=30
        flow=Mock();flow._last=None;flow._items=[child];flow._hgap=6;flow._vgap=6
        flow.cget.return_value=0
        for width in (220,900,40):
            flow.winfo_width.return_value=width
            ResponsiveFlow._reflow(flow)
            self.assertEqual(child.place.call_args.kwargs['width'],min(width,866))

    def test_wrapping_tracks_narrow_and_wide_parent(self):
        label=Mock();bind_responsive_wrap(label)
        callback=label.master.bind.call_args.args[1]
        for width in (160,600,80):
            callback(SimpleNamespace(width=width))
            self.assertEqual(label.configure.call_args.kwargs['wraplength'],width-24)


if __name__=='__main__':unittest.main()
