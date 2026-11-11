"""Synthetic browser check: PDF explanation is the default flow behind a pre-upload Groq notice.
Run from repo root: python scripts/check_ai_default_ui.py
Dev auth on localhost, temporary SQLite DB, explain endpoint mocked in the browser (no provider call).
"""
import importlib.util, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
spec = importlib.util.spec_from_file_location('s', Path(__file__).with_name('check_session_ui.py'))
src = Path(__file__).with_name('check_session_ui.py').read_text()
ns = {}
exec(src[:src.index('ROOT = Path')], ns)
make_pdf = ns['make_pdf']
ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, SLATE_DEV_AUTH='1', SLATE_STATE_URL='sqlite:///'+tmp+'/state.db')
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'agents.slate_api.app:app', '--host', '127.0.0.1', '--port', '8015'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try: urllib.request.urlopen('http://127.0.0.1:8015/v1/config'); break
            except Exception: time.sleep(.1)
        pdf = {'name':'synthetic.pdf','mimeType':'application/pdf','buffer':make_pdf(['Blake Example','Skills: SQL, communication'])}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH', '/usr/bin/google-chrome'), args=['--no-sandbox'])
            page = browser.new_page(); errors = []; calls = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def explain(route):
                calls.append(route.request.post_data_json)
                route.fulfill(status=200, content_type='application/json', body=json.dumps({'items':[{'text':'Synthetic summary.','sources':[{'line':'Skills: SQL, communication'}]}],'truncated':False,'charsSent':40,'charsTotal':40}))
            page.route('**/explain', explain)
            page.goto('http://127.0.0.1:8015/')
            page.locator('#devmail').fill('ack-a@example.com'); page.locator('#devgo').click()
            page.wait_for_function('token()!==""')
            assert page.locator('#aiconsent').count() == 0, 'optional checkbox must be gone'
            assert 'Groq' in page.locator('#aidisclose').inner_text()
            assert page.locator('#pdffile').is_disabled(), 'upload must wait for acknowledgment'
            assert calls == []
            page.screenshot(path='/tmp/slate-ai-preack.png', full_page=True)
            full = page.locator('#aidisclose').inner_text()
            assert 'Do not upload a PDF you do not want sent there' in full and 'paste your text instead' in full
            page.locator('#aiack').click()
            assert page.locator('#pdffile').is_enabled()
            page.locator('#pdffile').set_input_files(pdf)
            page.wait_for_function('document.querySelector("#pdfstatus").textContent.includes("Synthetic summary.")', timeout=15000)
            assert calls == [{'consent': True}], calls
            assert 'Blake Example' in page.locator('#resume').input_value()
            page.wait_for_timeout(3000)
            page.screenshot(path='/tmp/slate-ai-default.png', full_page=True)
            # second upload same session: default, no extra prompt
            page.locator('#pdffile').set_input_files(pdf)
            page.wait_for_function('document.querySelector("#pdfstatus").textContent.includes("Synthetic summary.")')
            page.wait_for_timeout(1500)
            assert len(calls) == 2
            # re-auth / session reset without reload: the full notice must be back, upload gated again
            page.evaluate('resetAccountState()')
            t = page.locator('#aidisclose').inner_text()
            assert 'Groq' in t and 'Do not upload a PDF you do not want sent there' in t and 'paste your text instead' in t, t
            assert 'Acknowledged' not in t
            assert page.locator('#aiack').is_visible() and page.locator('#pdffile').is_disabled()
            page.screenshot(path='/tmp/slate-ai-reauth.png', full_page=True)
            page.locator('#aiack').click(); assert 'Acknowledged' in page.locator('#aidisclose').inner_text()
            assert 'Do not upload a PDF you do not want sent there' in page.locator('#aidisclose').inner_text()
            # sign out then another account: acknowledgment does not carry over
            page.locator('#out').click(); page.wait_for_load_state()
            page.locator('#devmail').fill('ack-b@example.com'); page.locator('#devgo').click()
            page.wait_for_function('token()!==""')
            assert page.locator('#pdffile').is_disabled() and page.locator('#aiack').is_visible()
            # in-page account switch without reload: reset disables again
            page.locator('#aiack').click(); assert page.locator('#pdffile').is_enabled()
            page.evaluate('sessionStorage.setItem("slate_token","dev:other@example.com")')
            page.set_input_files('#pdffile', pdf)
            page.wait_for_timeout(800)
            assert len(calls) == 2, 'token change must block explain'
            assert errors == [], errors
            print('default-flow disclosure/ack checks passed; explain calls:', len(calls))
            browser.close()
    finally:
        proc.terminate()
