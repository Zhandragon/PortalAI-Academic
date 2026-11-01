"""Owned portable Chromium preview; no app bindings, persistence or network."""
import json
import queue
from pathlib import Path
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]


def main():
    raw=sys.stdin.readline(2*1024**2+1)
    if len(raw)>2*1024**2:raise ValueError('Preview payload too large')
    request=json.loads(raw)  # Parent assigns job ownership before this gate opens.
    from profile_context import CapturedProfile
    from web_runtime import prepare
    from artifact_document import preview_document
    from artifact_libraries import Libraries
    profile=CapturedProfile(ROOT);profile.check();executable=prepare(ROOT,browser=True)
    from playwright.sync_api import sync_playwright
    ended=threading.Event()
    def input_closed():
        try:sys.stdin.read(1)
        finally:ended.set()
    threading.Thread(target=input_closed,daemon=True,name='Preview-stdin').start()
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=str(executable),headless=bool(request.get('headless',False)),chromium_sandbox=True,
            args=['--disable-background-networking','--disable-extensions','--disable-sync','--no-first-run','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        try:
            embedded=bool(request.get('parent_hwnd')) and not request.get('headless',False)
            context=browser.new_context(offline=True,accept_downloads=False,service_workers='block',permissions=[],
                **({'no_viewport':True} if embedded else {'viewport':{'width':1000,'height':740}}))
            context.route('**/*',lambda route:route.abort('blockedbyclient'))
            # Register before any untrusted script can open another page.
            context.on('page',lambda new_page:new_page.close() if len(context.pages)>1 else None)
            page=context.new_page();page.set_default_timeout(10000)
            page.on('popup',lambda popup:popup.close())
            modules=Libraries(ROOT,profile.check).modules(request.get('dependencies',[]))
            page.set_content(preview_document(request['title'],request['kind'],request['content'],modules),wait_until='domcontentloaded')
            if request['kind'] in ('markdown','mermaid','react'):
                frame=page.frames[1]
                frame.wait_for_function("document.getElementById('portalai-render-status').dataset.state !== 'loading'",timeout=15000)
                if frame.locator('#portalai-render-status').get_attribute('data-state')!='ready':
                    raise ValueError(frame.locator('#portalai-render-status').inner_text()[:1500])
            host=None
            if embedded:
                from artifact_embed import EmbeddedWindow
                host=EmbeddedWindow(request['parent_hwnd'],browser,page)
            print(json.dumps({'ready':True,'embedded':bool(host),'network':'blocked','sandbox':'opaque-origin iframe with scripts only','browser_sandbox':True}),flush=True)
            deadline=time.monotonic()+1800
            while not ended.is_set() and not page.is_closed() and time.monotonic()<deadline:
                profile.check()
                if host:host.resize()
                page.wait_for_timeout(200)
        finally:browser.close()


if __name__=='__main__':main()
