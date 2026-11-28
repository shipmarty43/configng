"""Click the production panel in headless Chromium on a loopback-only test server."""
import json
import os
from pathlib import Path
import runpy
import subprocess
from threading import Thread
import time
import urllib.request

from werkzeug.serving import make_server


def check(app, chrome, temp, *, board="h618"):
    cdp_class = runpy.run_path(str(Path(__file__).resolve().parents[1] / "zero2w-browser-pixels.py"))["CDP"]
    with make_server("127.0.0.1", 0, app) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = temp / "chrome-profile"
        args = [chrome, "--headless", "--disable-gpu", "--no-first-run", "--disable-extensions",
                "--disable-background-networking", "--disable-sync", "--disable-component-update",
                "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=127.0.0.1",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cdp = None
        def until(check):
            end = time.monotonic() + 25
            while time.monotonic() < end and proc.poll() is None:
                if check():
                    return
                time.sleep(.1)
            raise RuntimeError("Browser check timed out: " + (str(cdp.evaluate("document.body?.innerText"))[:1200] if cdp else "startup"))
        try:
            portfile = profile / "DevToolsActivePort"
            until(lambda: portfile.is_file())
            port = int(portfile.read_text().splitlines()[0])
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as resp:
                tab = next(t for t in json.load(resp) if t["type"] == "page")
            cdp = cdp_class(tab["webSocketDebuggerUrl"])
            cdp.call("Network.enable")
            cdp.call("Network.setExtraHTTPHeaders", {"headers": {"Authorization": "Bearer " + os.environ["OPI_WEB_OPERATOR_TOKEN"]}})
            nav = cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/buses"})
            if "errorText" in nav:
                raise RuntimeError(nav["errorText"])
            js = cdp.evaluate
            until(lambda: js("!!document.querySelector('#preview:not(:disabled)')"))
            js("el('all-pins').click()")
            assert js("el('pins').querySelectorAll('tbody tr').length") == 28
            def preview(route):
                js(f"el('profile').value={json.dumps(route)}; el('profile').dispatchEvent(new Event('change')); el('preview').click()")
                until(lambda: js("!el('preview').disabled && !el('plan').hidden"))
            if board == "a733":
                assert js("el('board').textContent.includes('Zero 3W')")
                conflict, owner, pin = "a733-spi3-on", "Камера VIN", 24
                free, signal = "a733-i2c1-400000", "I²C1 SDA"
            else:
                conflict, owner, pin = "uart3-rtscts", "PWM1", 32
                free, signal = "i2c2-pi", "I²C2 SDA"
            preview(conflict)
            assert js(f"el('apply').disabled && el('issues').textContent.includes('{owner}') && el('issues').textContent.includes('{pin}')")
            preview(free)
            assert js(f"!el('apply').disabled && el('changes').textContent.includes('{signal}')")
            js("el('apply').click()")
            until(lambda: js(f"!el('undo').disabled && el('pins').textContent.includes('{signal}')"))
            js("el('undo').click()")
            until(lambda: js(f"!el('refresh').disabled && !el('pins').textContent.includes('{signal}')"))
            print(f"PASS Chromium {board}: 28 pins, blocked {conflict}, preview/apply {free} and one-click undo", flush=True)
        finally:
            if cdp:
                cdp.ws.close()
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            server.shutdown()
            thread.join()
