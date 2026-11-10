"""End-to-end browser test: onboarding → demo payment → VOICE capture (fake microphone) → save → activity → report → udhaar →
budgets → settings/theme → typed cash entry → offline queue + sync → wipe. Fails on any console error. Saves screenshots.
Run:  cd backend && pip install playwright && python -m playwright install chromium && cd .. && python e2e/run_e2e.py"""
import glob, json, os, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__)); BACK = os.path.join(ROOT, "..", "backend"); SHOTS = os.path.join(ROOT, "screenshots")
PORT = int(os.environ.get("E2E_PORT", "8791")); URL = f"http://127.0.0.1:{PORT}"
os.makedirs(SHOTS, exist_ok=True)
env = dict(os.environ, GNANI_MOCK="true", DB_PATH=os.path.join(tempfile.mkdtemp(), "e2e.db"), DEMO_ENABLED="true", RATE_LIMIT_PER_MIN="2000", LLM_PROVIDER="rules", PYTHONPATH=BACK)
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], cwd=BACK, env=env)
for _ in range(50):
    try: urllib.request.urlopen(URL + "/api/v1/health"); break
    except Exception: time.sleep(0.2)
fails, errors = [], []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else "")); (not cond) and fails.append(name)

exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, permissions=["microphone"], locale="en-IN", timezone_id="Asia/Kolkata")
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and "ERR_INTERNET_DISCONNECTED" not in m.text and errors.append("console: " + m.text))  # offline errors are expected while the offline phase runs
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        pg.on("dialog", lambda d: d.accept())
        shot = lambda n: pg.screenshot(path=f"{SHOTS}/{n}.png")
        def api(path, method="GET", body=None):
            return pg.evaluate("""async ([p,m,b])=>{const r=await fetch('/api/v1'+p,{method:m,headers:{Authorization:'Bearer '+localStorage.hb_token,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json()}""", [path, method, body])
        T = lambda txt, **k: pg.get_by_text(txt, exact=k.get("exact", False)).first
        # 1 onboarding
        pg.goto(URL); pg.wait_for_selector(".ob"); check("onboarding shown", "Your payments, in your words" in pg.inner_text("body")); shot("01-onboarding-welcome")
        pg.click("[data-act=ob-next]"); pg.wait_for_selector("text=How do you speak?"); pg.click("text=తెలుగు + English"); shot("02-onboarding-language")
        pg.click("[data-act=ob-next]"); pg.wait_for_selector("text=How should I ask?"); shot("03-onboarding-ask")
        pg.click("[data-act=ob-next]"); pg.wait_for_selector("text=Detect payments automatically"); check("web explains app-only auto-detect", "Android app" in pg.inner_text("body")); shot("04-onboarding-detect")
        pg.click("[data-act=ob-next]"); pg.wait_for_selector("text=HisaabBol >> nth=0"); pg.wait_for_selector("text=Try a demo payment >> nth=0")
        check("speaking language saved to server", api("/settings")["language_hint"] == "te-IN,en-IN"); shot("05-home-empty")
        # 2 demo payment -> voice capture
        pg.click("[data-act=demo] >> nth=0"); pg.wait_for_selector("text=Zomato via HDFC UPI"); shot("06-demo-sheet"); pg.click("text=Zomato via HDFC UPI")
        pg.wait_for_selector(".cap"); check("capture shows amount+payee", "₹450" in pg.inner_text(".cap") and "ZOMATO" in pg.inner_text(".cap")); shot("07-capture-idle")
        pg.click("[data-act=mic]"); pg.wait_for_selector(".mic.rec"); check("recording state", "Listening" in pg.inner_text(".cap")); time.sleep(1.3); shot("08-capture-recording")
        pg.click("[data-act=mic]"); pg.wait_for_selector("text=I heard", timeout=15000)
        check("voice → draft (mock STT) categorised Food & Dining", "Food & Dining" in pg.inner_text(".cap") and "chai aur samosa" in pg.inner_text(".cap")); shot("09-capture-draft")
        pg.click("[data-act=cap-save]"); pg.wait_for_selector(".check"); shot("10-capture-saved"); pg.wait_for_selector("text=Recent", timeout=8000)
        check("saved entry appears on home", "₹450" in pg.inner_text("#view"))
        # 3 sample data + activity
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("text=Theme"); shot("11-settings")
        pg.click("[data-act=seed] >> nth=0"); time.sleep(0.8)
        pg.goto(URL + "/#/activity"); pg.wait_for_selector(".tx"); check("activity lists entries", pg.locator(".tx").count() >= 20); shot("12-activity")
        pg.fill("#q", "zomato"); time.sleep(1.0); check("search filters", 0 < pg.locator(".tx").count() < 30)
        pg.locator(".tx").first.click(); pg.wait_for_selector(".sheet [data-pick]"); shot("13-edit-sheet"); pg.click(".sheet [data-pick]"); pg.click(".sheet >> text=Gifts & Donations"); pg.click(".sheet [data-save]"); time.sleep(0.8)
        check("category edit persisted", api("/transactions?category=Gifts%20%26%20Donations&q=zomato")["total"] >= 1)
        # 4 report
        pg.goto(URL + "/#/report"); pg.wait_for_selector(".donut svg"); check("report has donut + insights", pg.locator(".donut circle").count() > 3 and "What I noticed" in pg.inner_text("#view")); shot("14-report")
        pg.click("[data-act=mprev]"); pg.wait_for_selector(".donut svg"); shot("15-report-prev-month")
        # 5 person payee -> udhaar
        pg.goto(URL + "/#/more"); pg.wait_for_selector("[data-act=demo]"); pg.click("[data-act=demo] >> nth=0"); pg.click("text=Person payee (Ramesh)"); pg.wait_for_selector(".cap")
        check("person payee asks who/why + shows chips", "Who is this for" in pg.inner_text(".cap") and "Lent" in pg.inner_text(".cap")); shot("16-capture-person")
        pg.click("[data-act=quick][data-cat='Lent (udhaar)']"); pg.wait_for_selector("text=I heard"); check("udhaar pill shown", "🤝" in pg.inner_text(".cap")); pg.click("[data-act=cap-save]"); pg.wait_for_selector(".check")
        pg.goto(URL + "/#/udhaar"); pg.wait_for_selector("text=You will get"); check("udhaar ledger has Ramesh", "Ramesh" in pg.inner_text("#view") or "RAMESH" in pg.inner_text("#view")); shot("17-udhaar")
        # 6 budgets
        pg.goto(URL + "/#/budgets"); pg.click("[data-act=add-budget]"); pg.fill("#bl", "30000"); pg.click(".sheet [data-ok]"); pg.wait_for_selector(".bar"); check("overall budget created", len(api("/budgets")["items"]) >= 1); shot("18-budgets")
        # 7 typed cash entry
        pg.goto(URL + "/#/home"); pg.wait_for_selector("[data-act=open-cap]"); pg.click("nav .fab"); pg.wait_for_selector(".cap"); pg.click("[data-act=cap-type]"); pg.fill("#typed", "chai 20 rupees"); pg.click("[data-act=cap-text]")
        pg.wait_for_selector("text=I heard"); check("cash typed → amount ₹20 from speech", "20" in pg.inner_text(".cap") and "Food & Dining" in pg.inner_text(".cap")); shot("19-cash-draft")
        # 8 offline queue: draft online, save offline, sync on reconnect
        tok = pg.evaluate("localStorage.hb_token")
        def server_total():  # ask the server directly (not through the offline browser)
            rq = urllib.request.Request(URL + "/api/v1/transactions?limit=1", headers={"Authorization": "Bearer " + tok}); return json.load(urllib.request.urlopen(rq))["total"]
        before = server_total(); ctx.set_offline(True); pg.click("[data-act=cap-save]"); pg.wait_for_selector("text=Saved offline", timeout=5000); shot("20-offline-queued")
        check("nothing reached the server while offline", server_total() == before); ctx.set_offline(False); time.sleep(2.5)
        check("outbox synced after reconnect (exactly one new entry)", server_total() == before + 1)
        # 9 look & feel
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("text=Theme"); pg.click("[data-act=theme][data-v=dark]"); pg.click("[data-act=accent][data-v=Teal]"); time.sleep(0.3); shot("21-settings-dark-teal")
        pg.goto(URL + "/#/home"); pg.wait_for_selector("text=Recent"); check("dark theme + teal accent applied", pg.evaluate("document.documentElement.dataset.theme") == "dark" and pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent')").strip() == "#0f766e"); shot("22-home-dark")
        pg.goto(URL + "/#/more"); pg.wait_for_selector("text=Diagnostics"); shot("23-more"); pg.goto(URL + "/#/diagnostics"); pg.wait_for_selector("text=Gnani usage"); check("diagnostics counts STT call", "STT" in pg.inner_text("#view")); shot("24-diagnostics")
        pg.click("nav [data-go=home]"); pg.evaluate("localStorage.setItem('hb_prefs', JSON.stringify({...JSON.parse(localStorage.hb_prefs),ui:'hi'}))"); pg.reload(); pg.wait_for_selector("text=नमस्ते"); check("Hindi UI", True); shot("25-home-hindi")

        pg.evaluate("localStorage.setItem('hb_prefs', JSON.stringify({...JSON.parse(localStorage.hb_prefs),ui:'en'}))"); pg.goto(URL + "/#/home"); pg.reload(); pg.wait_for_selector("text=Hello")
        # 9b undo after save puts the payment back in "needs a note"
        pg.goto(URL + "/#/more"); pg.click("[data-act=demo] >> nth=0"); pg.click("text=GPay notification"); pg.wait_for_selector(".cap")
        pg.click("[data-act=cap-type]"); pg.fill("#typed", "vegetables"); pg.click("[data-act=cap-text]"); pg.wait_for_selector("text=I heard"); pg.click("[data-act=cap-save]"); pg.wait_for_selector(".toast button", timeout=8000); shot("26-undo-toast")
        pend0 = len(api("/captures?status=pending")["items"]); pg.click(".toast button"); time.sleep(1.0)
        check("undo returns the payment to pending", len(api("/captures?status=pending")["items"]) == pend0 + 1)
        # 9c reminders on home
        api("/udhaar", "POST", {"person": "Asha", "direction": "i_lent", "amount_paise": 25000, "due_date": "2020-01-01"})
        pg.goto(URL + "/#/home"); pg.reload(); pg.wait_for_selector("text=Reminders"); check("udhaar reminder on home", "Asha" in pg.inner_text("#view")); shot("27-home-reminders")
        # 9d learned shops
        api("/merchants", "PUT", {"merchant": "Ramu Tea Stall", "category": "Food & Dining", "auto_apply": True})
        pg.goto(URL + "/#/shops"); pg.wait_for_selector("text=ramu tea stall", timeout=5000); shot("28-shops")
        pg.locator(".sw input").first.evaluate("e => e.click()"); time.sleep(0.6)
        check("shop auto-apply toggle persists", any(x["merchant"] and not x["auto_apply"] for x in api("/merchants")["items"]) )
        # 9e app lock
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("text=App lock")
        pg.locator("[data-in=lock]").evaluate("e => e.click()"); pg.wait_for_selector(".pad")
        for _ in range(2):
            for d in "1234": pg.click(f'.pad [data-k="{d}"]')
            time.sleep(0.4)
        check("PIN saved (hash only)", bool(pg.evaluate("localStorage.getItem('hb_lock')")) and "1234" not in pg.evaluate("localStorage.getItem('hb_lock')"))
        pg.reload(); pg.wait_for_selector(".lock"); shot("29-lock")
        for d in "9999": pg.click(f'.lock [data-k="{d}"]')
        time.sleep(0.5); check("wrong PIN keeps it locked", pg.locator(".lock").count() == 1)
        for d in "1234": pg.click(f'.lock [data-k="{d}"]')
        pg.wait_for_selector(".lock", state="detached", timeout=5000); check("right PIN unlocks", True)
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("text=App lock"); pg.locator("[data-in=lock]").evaluate("e => e.click()"); pg.wait_for_selector(".pad")
        for d in "1234": pg.click(f'.pad [data-k="{d}"]')
        time.sleep(0.6); check("app lock can be turned off", pg.evaluate("localStorage.getItem('hb_lock')") is None)
        # 9f backup key + restore on a "new phone"
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("[data-act=backup]"); pg.click("[data-act=backup] >> nth=0"); pg.wait_for_selector(".keybox")
        key = pg.inner_text(".keybox").strip(); check("backup key shown", key == pg.evaluate("localStorage.hb_token") and key.startswith("hb_")); shot("30-backup-key")
        ctx2 = b.new_context(viewport={"width": 390, "height": 844}, locale="en-IN"); p2 = ctx2.new_page(); p2.goto(URL); p2.wait_for_selector(".ob"); p2.click("[data-act=restore]"); p2.fill("#rk", "hb_wrong"); p2.click(".sheet [data-ok]"); time.sleep(0.6)
        check("bad key rejected", p2.locator(".ob").count() == 1); p2.fill("#rk", key); p2.click(".sheet [data-ok]"); p2.wait_for_selector("text=Recent", timeout=8000)
        check("restore on a new device brings back the data", "₹" in p2.inner_text("#view")); ctx2.close()
        # 9g hardware Back (sent by the Android shell) closes capture, then returns home
        pg.goto(URL + "/#/home"); pg.wait_for_selector("nav .fab"); pg.click("nav .fab"); pg.wait_for_selector(".cap")
        pg.evaluate("window.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'back'})}))"); time.sleep(0.5)
        check("Back message closes capture screen", pg.locator(".cap").count() == 0)
        tok2 = pg.evaluate("localStorage.hb_token"); rq = urllib.request.Request(URL + "/api/v1/export/json", headers={"Authorization": "Bearer " + tok2}); bk = json.load(urllib.request.urlopen(rq))
        check("full JSON backup contains data", bk["app"] == "HisaabBol" and len(bk["transactions"]) > 20 and len(bk["learned_shops"]) >= 1)
        # 10 wipe
        pg.goto(URL + "/#/settings"); pg.wait_for_selector("[data-act=wipe]"); pg.click("[data-act=wipe]"); time.sleep(0.8); check("delete-all wipes data", api("/transactions")["total"] == 0)
        # PWA basics
        check("manifest + service worker reachable", pg.evaluate("fetch('/manifest.webmanifest').then(r=>r.ok)") and pg.evaluate("fetch('/sw.js').then(r=>r.ok)"))
        b.close()
except Exception as ex:  # keep evidence for debugging
    try: pg.screenshot(path=f'{SHOTS}/FAIL-state.png'); print('PAGE TEXT:', pg.inner_text('body')[:700].replace('\n',' | '), 'URL:', pg.url)
    except Exception: pass
    raise
finally:
    srv.terminate()
check("no console/page errors", not errors, "; ".join(errors[:5]))
print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}"); sys.exit(1 if fails else 0)
