"""Isolated Tk tour check: no app account, backend, downloads or settings."""
import sys, tempfile, unittest, os
from pathlib import Path
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ApplicationSources/Windows/PortalAI/ControlCenter'))
from app_tour import AppTour, STEPS

class TourChecks(unittest.TestCase):
    def test_navigation_and_skip(self):
        app=tk.Tk();app.geometry('1000x720+20000+20000')
        palette={'bg':'#EEE7DC','panel':'#F8F3EA','panel2':'#E6DCCB','text':'#202224','muted':'#6E665E','accent':'#3E91A2','button':'#E6DCCB','button_hover':'#D9CBB3','gold_mid':'#A87D32','gold_shine':'#D9BE78','border':'#A87D32'}
        state=['welcome'];calls=[]
        def go(page):state[0]=page;calls.append(page)
        try:
            with tempfile.TemporaryDirectory() as folder:
                tour=AppTour(app,folder,lambda:palette,go,lambda:state[0]);app.update()
                tour.offer_when_ready();app.update();self.assertIsNotNone(tour.dialog)
                tour.close();app.update();self.assertTrue(tour.marker.exists());self.assertIsNone(tour.dialog)
                state[0]='settings';tour.start();app.update();self.assertEqual(state[0],'welcome')
                for button,_enabled in tour.dialog.buttons:
                    self.assertTrue(button.winfo_ismapped(),button.cget('text'))
                    self.assertGreater(button.winfo_height(),20)
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),tour.dialog.surface.card.winfo_rooty()+tour.dialog.surface.card.winfo_height())
                if os.environ.get('PORTALAI_TOUR_PREVIEW_DIR'):
                    from modal_backdrop import snapshot_host
                    from PIL import Image
                    snapshot=snapshot_host(app,app,palette)
                    self.assertIsNotNone(snapshot)
                    folder=Path(os.environ['PORTALAI_TOUR_PREVIEW_DIR']);folder.mkdir(parents=True,exist_ok=True)
                    Image.frombytes('RGB',(snapshot.width,snapshot.height),snapshot.rgb).save(folder/'tour-light.png')
                tour.move(1);app.update();tour.move(-1);app.update();self.assertEqual(tour.index,0)
                for i in range(1,len(STEPS)):
                    tour.move(1);app.update();self.assertEqual(state[0],STEPS[i][0]);self.assertFalse(tour.dialog.closed)
                tour.close();app.update();self.assertEqual(state[0],'settings');self.assertIsNone(app._portalai_modal_guard.surface)
                tour.offer_when_ready();self.assertIsNone(tour.dialog)
                self.assertTrue(set(calls).issubset({p for p,_,_ in STEPS}))
        finally:app.destroy()

if __name__=='__main__':unittest.main()
