"""Verify the installed native web runtime. --launch checks Chromium without network or accounts."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--launch',action='store_true');args=parser.parse_args()
    from web_runtime import prepare,platform_id
    layer=prepare(ROOT);import pypdf,playwright
    result={'platform':platform_id(),'packages':str(layer/'packages'),'pypdf':pypdf.__version__,'browser_launched':False}
    if args.launch:
        executable=prepare(ROOT,browser=True)
        node=os.environ['PLAYWRIGHT_NODEJS_PATH']
        probe=subprocess.run([str(node),'--version'],capture_output=True,text=True,timeout=20)
        if probe.returncode:raise RuntimeError('Browser driver failed: '+str(probe.returncode)+' '+probe.stderr[-2000:])
        result['node_version']=probe.stdout.strip()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=str(executable),headless=True,chromium_sandbox=True)
            try:
                page=browser.new_page();page.set_content('<title>PortalAI runtime check</title><h1>WEB_RUNTIME_OK</h1>')
                if page.locator('h1').inner_text()!='WEB_RUNTIME_OK':raise RuntimeError('Browser probe failed')
                result.update(browser_launched=True,browser_version=browser.version)
            finally:browser.close()
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
