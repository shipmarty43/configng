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


def check(app, chrome, temp, *, board="h618", observe=None, protect=None, spi1=False, reverse_spi1=False, reverse_uart=False):
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
            js("if (!el('all-pins').checked) el('all-pins').click()")
            assert js("el('pins').querySelectorAll('tbody tr').length") == 28
            def preview(route):
                js(f"el('profile').value={json.dumps(route)}; el('profile').dispatchEvent(new Event('change')); el('preview').click()")
                until(lambda: js("!el('preview').disabled && !el('plan').hidden"))
            if board == "a733":
                assert js("el('pins').textContent.includes('SPI2 CS1') && el('pins').textContent.includes('S_PWM0-2')")
                assert js("el('board').textContent.includes('Zero 3W')")
                conflict, owner, pin = "a733-spi3-on", "Камера VIN", 24
                free, signal = "a733-i2c1-400000", "I²C1 SDA"
            elif spi1:
                conflict, owner, pin = "shared", "I²C3", 18
            elif observe:
                conflict, owner, pin = "uart2-rtscts", "I²C1", 3
            else:
                conflict, owner, pin = "uart3-rtscts", "PWM1", 32
                free, signal = "i2c2-pi", "I²C2 SDA"
            def preview_conflict():
                preview(conflict)
                assert js(f"el('apply').disabled && el('issues').textContent.includes('{owner}') && el('issues').textContent.includes('{pin}')")
            if not (reverse_spi1 or reverse_uart):
                preview_conflict()
            if observe:
                if board == "a733":
                    routes = {"19":["I²C2 SDA","SPI3 MOSI"], "23":["I²C2 SCL","SPI3 CLK"],
                              "24":["Камера VIN","SPI3 CS0"]}
                    parts = ("камеру VIN","I²C2","SPI3")
                elif spi1:
                    routes = {"18":["I²C3 SCL","nRF24 CE"], "24":["I²C3 SDA","SPI1 CS2"],
                              "19":["I²C4 SDA","SPI1 MOSI"], "23":["I²C4 SCL","SPI1 CLK"]}
                    parts = ("I²C3","I²C4","SX1262","CC1101","nRF24")
                else:
                    routes = {"3":["I²C1 SDA","UART2 CTS"], "5":["I²C1 SCL","UART2 RTS"],
                              "15":["I²C0 SCL","UART2 TX"], "22":["I²C0 SDA","UART2 RX"]}
                    parts = ("I²C0","I²C1","UART2")
                def owners(live_new, saved_new):
                    rows = js("Array.from(el('pins').querySelectorAll('tbody tr'), r => "
                              "[r.cells[0].textContent, r.cells[2].textContent, r.cells[3].textContent])")
                    pins = {pin:(live,saved) for pin,live,saved in rows}
                    return all(pin in pins and names[live_new] in pins[pin][0]
                               and names[saved_new] in pins[pin][1] for pin,names in routes.items())
                def rates(section, active):
                    if active:
                        rows = js(f"Array.from(el('{section}').querySelectorAll('tbody tr'), r => Array.from(r.cells,c => c.textContent))")
                        assert [(r[0],r[1],r[3],r[4]) for r in rows if r[0] in ("1","2")] == [
                            ("1","CC1101","1000000","1000000"),("2","nRF24","4000000","4000000")], rows
                    else:
                        body = js(f"el('{section}').textContent")
                        assert all(f"CS{cs} · сохранено {hz} Гц" in body for cs,hz in ((1,1000000),(2,4000000)))
                if spi1:
                    js("document.querySelector('details').open=true")
                def pi_rates(live_uart, saved_uart):
                    rows = js("Array.from(el('i2c-rates').querySelectorAll('tbody tr'),r=>Array.from(r.cells,c=>c.textContent))")
                    assert rows == [[bus, "—" if live_uart else hz, ("сохранено " if saved_uart else "")+hz]
                                    for bus,hz in (("I²C0","200000 Гц"),("I²C1","400000 Гц"))], rows
                if reverse_spi1 or reverse_uart:
                    assert owners(True,True) and js("el('undo').disabled")
                    if spi1:
                        rates("current",True)
                        preview("shared-to-i2c34-ph")
                        rates("candidate",False)
                    else:
                        pi_rates(True,True)
                        preview("uart2-rtscts-to-i2c01-pi")
                        summary = js("el('candidate').textContent")
                        assert "I²C0 · 200000 Гц" in summary and "I²C1 · 400000 Гц" in summary
                    assert js("!el('apply').disabled")
                    diff = js("el('changes').textContent")
                    assert all(name in diff for pair in routes.values() for name in pair)
                    js("el('apply').click()")
                    until(lambda: js("!el('refresh').disabled") and owners(True,False))
                    if spi1: rates("current",False)
                    else: pi_rates(True,False)
                    observe(False)
                    js("el('refresh').click()")
                    until(lambda: js("!el('refresh').disabled") and owners(False,False))
                    if reverse_uart: pi_rates(False,False)
                    preview_conflict()
                assert owners(False,False)
                if spi1: rates("current",False)
                offer = js("el('issues').querySelector('button').textContent")
                assert all(part in offer for part in parts)
                js("el('issues').querySelector('button').click()")
                until(lambda: js("!el('apply').disabled"))
                assert all(p in js("el('issues').textContent") for p in parts)
                diff = js("el('changes').textContent")
                assert all(name in diff for pair in routes.values() for name in pair)
                if spi1: rates("candidate",True)
                js("el('apply').click()")
                until(lambda: js("!el('undo').disabled") and owners(False,True))
                if spi1: rates("current",True)
                observe(True)
                js("el('refresh').click()")
                until(lambda: js("!el('undo').disabled") and owners(True,True))
                if spi1: rates("live",True)
                if reverse_uart:
                    pi_rates(True,True)
                    print("PASS Chromium: UART2 → I2C0/I2C1 and explicit return; independent 200000/400000 Hz verified in preview, next-boot and live panels without undo",flush=True)
                    return
                if reverse_spi1:
                    print("PASS Chromium: standalone SPI1 → I2C3/4 PH and explicit return; verified CS1/CS2 at preview, save and simulated boot",flush=True)
                    return
                js("el('undo').click()")
                until(lambda: js("!el('refresh').disabled") and owners(True,False))
                observe(False)
                js("el('refresh').click()")
                until(lambda: js("!el('refresh').disabled") and owners(False,False))
                if spi1: rates("current",False)
                print(f"PASS Chromium {board}: {conflict} handoff and one undo, checked before/after/live owners on pins {', '.join(routes)}",flush=True)
                if protect:
                    assert_unchanged = protect()
                    js("el('refresh').click()")
                    until(lambda: js("!el('refresh').disabled && el('pins').textContent.includes('DFR0528')"))
                    preview(conflict)
                    assert js("el('apply').disabled && el('issues').textContent.includes('DFR0528') && !el('issues').querySelector('button')")
                    assert owners(False,False)
                    assert_unchanged()
                    print("PASS Chromium: DFR0528 displayed, no partial offer, save disabled; boot files and history unchanged",flush=True)
                return
            preview(free)
            assert js(f"!el('apply').disabled && el('changes').textContent.includes('{signal}')")
            js("el('apply').click()")
            until(lambda: js(f"!el('undo').disabled && Array.from(el('pins').querySelectorAll('tbody tr')).some(r => r.cells[3].textContent.includes('{signal}'))"))
            js("el('undo').click()")
            until(lambda: js(f"!el('refresh').disabled && !Array.from(el('pins').querySelectorAll('tbody tr')).some(r => r.cells[3].textContent.includes('{signal}'))"))
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
