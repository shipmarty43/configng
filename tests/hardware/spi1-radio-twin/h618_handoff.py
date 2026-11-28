"""H618 I²C0 + I²C1 → UART2 RTS/CTS acceptance on a private boot tree."""
import hashlib
import os
import shutil
import subprocess
from unittest.mock import patch

from dt_clock_overlay import replace_env_names, tokens, write_selection
from i2c_clocks import BUSES, DEFAULT, PARKED, parked
from header_panel import UART_TO_PI, UART_TO_PI_LABEL
from modules.system.system_module import SystemModule
from uart_routes import FLOW_PROP, address, cells, enabled, prepare, read_tree, token

TARGET = "uart2-rtscts"
COMBINED = TARGET + "+i2c0+i2c1"
PINS = {3:("I²C1 SDA","UART2 CTS"), 5:("I²C1 SCL","UART2 RTS"),
        15:("I²C0 SCL","UART2 TX"), 22:("I²C0 SDA","UART2 RX")}


def dialog(helper, get, undo, protected, *, group="UART", target=TARGET, owners="I²C0 и I²C1", direct=False, clocks=()):
    import pexpect
    state = get()
    groups = list(dict.fromkeys(o["group"] for o in state["choices"]))
    routes = [o["id"] for o in state["choices"] if o["group"] == group]
    down, yes = "\x1bOB", "\x1bOD\r"
    with pexpect.spawn(str(helper), ["dialog"], encoding="utf-8", timeout=25, dimensions=(36,126),
                       env=os.environ | {"LC_ALL":"C.UTF-8","TERM":"xterm"}) as tty:
        tty.expect_exact("40-контактная")
        if undo:
            tty.send(down * (len(groups)+1) + "\r")
        else:
            tty.send(down * (groups.index(group)+1) + "\r")
            tty.expect_exact("CC1101 + nRF24" if group == "SPI1" else "Выберите маршрут для предпросмотра")
            tty.send(down * routes.index(target) + "\r")
            if protected:
                tty.expect_exact("Применение заблокировано")
                tty.expect_exact("DFR0528")
                tty.send("\r")
            else:
                if not direct:
                    tty.expect_exact("Предпросмотр перехода?")
                    tty.expect_exact(owners)
                    tty.send(yes)
                tty.expect_exact("Сохранить для следующей загрузки?")
                tty.expect_exact(owners)
                if group == "SPI1":
                    tty.expect_exact("После применения")
                    if direct:
                        tty.expect_exact("CS1 сохранено 1000000 Гц")
                        tty.expect_exact("CS2 сохранено 4000000 Гц")
                    else:
                        tty.expect_exact("CC1101")
                        tty.expect_exact("1000000 Гц")
                        tty.expect_exact("nRF24")
                        tty.expect_exact("4000000 Гц")
                for rate in clocks:
                    tty.expect_exact(f"{rate} Гц")
                tty.send(yes)
        if not protected:
            tty.expect_exact("Сохранено для")
            tty.send("\r")
        tty.expect(pexpect.EOF)
    assert tty.exitstatus == 0


def check_handoff(tmp, helper, repo, app, *, reverse=False):
    boot = tmp/"boot"
    env = boot/"armbianEnv.txt"
    folder = boot/"overlay-user"
    folder.mkdir(exist_ok=True)
    env.write_text("# preserve unrelated settings and token order\nrootdev=UUID=twin\n"
                   "overlay_prefix=sun50i-h616\noverlays=i2c0-pi pwm1-pi11 i2c1-pi\n")
    rates = {"twi0":200000 if reverse else 100000, "twi1":400000}
    for bus, hz in rates.items():
        subprocess.run([helper,"clock",bus,str(hz)],check=True,stdout=subprocess.DEVNULL)
    baseline = env.read_bytes()
    dfr = "zero2w-dfr0528"
    subprocess.run(["dtc","-q","-@","-o",folder/(dfr+".dtbo"),
                    repo/"hardware/dfrobot-ups"/(dfr+".dts")],check=True)
    journal = boot/"armbianEnv.txt.spi1-panel-backups"
    web = app.test_client()

    def get():
        response = web.get("/api/buses",auth=("viewer","read"))
        assert response.status_code == 200, response.json
        return response.json

    def post(action, body, status=200, *, viewer=False):
        auth = ("viewer","read") if viewer else ("operator","write")
        response = web.post("/api/buses/"+action,auth=auth,headers={"X-OPi-Panel":"1"},json=body)
        assert response.status_code == status, (action,body,response.json)
        return response.json

    def preview(key):
        return post("preview",{"profile":key},viewer=True)

    def history():
        return set(journal.glob("change.*"))

    def files():
        return {p.relative_to(boot):p.read_bytes() for p in boot.rglob("*")
                if p.is_file() and p.name != "armbianEnv.txt.overlay.lock"}

    boot_number = 0
    def reboot(uart, protected=False):
        nonlocal boot_number
        boot_number += 1
        subprocess.run([helper,"boot-dtb"],check=True)
        tree = read_tree(tmp/"booted.dtb")
        port = address("uart2")
        assert enabled(tree,port) == uart
        if uart:
            assert tree[port][FLOW_PROP] == b"h618\0" and "uart-has-rtscts" in tree[port]
        for bus,rate in rates.items():
            path = BUSES[bus]
            assert enabled(tree,path) == (not uart)
            if not uart:
                assert cells(tree[path]["clock-frequency"]) == [rate]
        if protected:
            ups = BUSES["twi1"]+"/ups@10"
            assert enabled(tree,ups) and tree[ups]["compatible"] == b"dfrobot,dfr0528\0"
        # Materialize exactly the composed OF tree for the next live inventory.
        root = tmp/f"boot-{boot_number}"
        for node,props in tree.items():
            path = root/node.lstrip("/")
            path.mkdir(parents=True,exist_ok=True)
            for k,v in props.items():
                (path/k).write_bytes(v)
        (tmp/"next").symlink_to(root)
        (tmp/"next").replace(tmp/"live")
        state = get()
        for when in ("live","current"):
            shown = state[when]["pi_clocks"]
            expected_rates = {} if uart and when=="live" else {
                bus:dict(hz=rate,saved=uart) for bus,rate in rates.items()}
            assert shown == expected_rates, (when,shown,expected_rates)
            pins = {r["pin"]:r["owners"] for r in state[when]["pins"]}
            for n,pair in PINS.items():
                expected = pair[uart] + (" · DFR0528" if protected and n in (3,5) else "")
                assert [o["label"] for o in pins[n]] == [expected], (when,n,pins[n])
            assert pins[32][0]["label"]=="PWM1"

    def ups(on):
        env.write_bytes(baseline)
        if on:
            text = env.read_text()
            write_selection(text,env,[*tokens(text),dfr])
        reboot(False,protected=on)

    module = SystemModule()
    menu = dict(module.get_menu_items())["Шины и контакты"]
    def urwid(action):
        def choose(title,items):
            if title.startswith("Шины и контакты"):
                return items.index("Откатить последнее изменение" if action=="undo" else "UART")
            if title.startswith("UART ·"):
                return next(i for i, s in enumerate(items) if "UART2 · RTS/CTS · 15/22/5/3" in s)
            if action=="protected":
                assert "Применение заблокировано" in title and "DFR0528" in title and items==["Назад"]
                return 0
            if "Конфликт" in title:
                assert all(f"Вывод {pin} (" in title for pin in PINS)
                return next(i for i,s in enumerate(items) if "I²C0 и I²C1" in s)
            assert "I²C0 и I²C1" in title and all(a in title and b in title for a,b in PINS.values())
            return items.index("Назад" if action=="cancel" else "Сохранить для следующей загрузки")
        with patch.object(module,"show_menu",side_effect=choose), patch.object(module,"show_message"), \
             patch.object(module,"show_error",side_effect=AssertionError):
            menu()

    def native(action):
        if os.environ.get("PANEL_TEST_DIALOG"):
            dialog(helper, get, action=="undo", action=="protected")
        else:
            cmd = subprocess.run([helper,"native"],env=os.environ | {
                "PANEL_GROUP":"undo" if action=="undo" else "UART","PANEL_CHOICE":TARGET,"PANEL_CONFIRM":"yes"},
                capture_output=True,check=True,text=True)
            assert ("DFR0528" if action=="protected" else "Сохранено") in cmd.stdout, cmd.stdout

    def observe(uart):
        new = history() - prior
        if uart:
            entry, = new
            assert (entry/"before").read_bytes()==baseline
            assert (entry/"after").read_bytes()==env.read_bytes()!=baseline
        else:
            assert len(new)==2 and env.read_bytes()==baseline
        reboot(uart)

    if reverse:
        check_reverse(tmp, helper, app, get, post, preview, urwid, native, reboot, rates)
        print("DTB SHA256",hashlib.sha256((boot/"dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb").read_bytes()).hexdigest(),flush=True)
        return

    ups(False)
    prior = history()
    unchanged = files()
    offer = preview(TARGET)
    assert not offer["token"] and offer["alternative"]["id"] == COMBINED
    plan = preview(COMBINED)
    assert plan["token"] and not plan["issues"]
    changes = {r["pin"]:(r["before"][0]["label"],r["after"][0]["label"]) for r in plan["changes"]}
    assert changes == PINS
    urwid("cancel")
    assert files()==unchanged
    for name in (TARGET+"+i2c0", TARGET+"+i2c1", COMBINED+"+pwm1"):
        assert not preview(name)["token"]
        post("apply",{"profile":name,"token":plan["token"]},409)
    post("preview",{"profile":COMBINED+"+i2c0"},400)
    post("apply",{"profile":COMBINED,"token":plan["token"]},403,viewer=True)
    assert files()==unchanged and history()==prior
    # A UPS added after a clean preview must block even the original token.
    ups(True)
    protected = files()
    for name in (TARGET, COMBINED):
        deny = preview(name)
        assert not deny["token"] and deny["alternative"] is None
        assert any("DFR0528" in problem for problem in deny["issues"])
    post("apply",{"profile":COMBINED,"token":plan["token"]},409)
    urwid("protected")
    native("protected")
    assert files()==protected and history()==prior
    print("PASS DFR0528 at 0x10: Web API and TUI block the full UART2 transition, including stale apply; both buses and clocks, UPS, journal and installed overlays intact",flush=True)
    ups(False)
    for frontend in (urwid,native):
        prior = history()
        frontend("save")
        observe(True)
        frontend("undo")
        observe(False)
        print(f"PASS {frontend.__name__}: one journal entry releases I²C0/I²C1 for UART2 RTS/CTS; one undo, exact env, 100/400 kHz and pins 3/5/15/22 after simulated boots",flush=True)
    if os.environ.get("PANEL_TEST_CHROMIUM"):
        from panel_browser import check
        prior = history()
        def protect():
            ups(True)
            saved = files()
            changes = history()
            def assert_unchanged():
                assert files() == saved and history() == changes
            return assert_unchanged
        check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,observe=observe,protect=protect)
    print("DTB SHA256",hashlib.sha256((boot/"dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb").read_bytes()).hexdigest(),flush=True)

def check_reverse(tmp, helper, app, get, post, preview, forward_urwid, forward_native, reboot, rates):
    boot = tmp/"boot"
    env = boot/"armbianEnv.txt"
    journal = boot/"armbianEnv.txt.spi1-panel-backups"
    # Seed actual clock overrides and enter the UART2 profile via the supported forward handoff.
    p = preview(COMBINED)
    post("apply", {"profile":COMBINED, "token":p["token"]})
    original = env.read_bytes()
    saved = parked(original.decode())
    assert {bus:hz for bus,(_,hz) in saved.items()} == rates
    seed = tmp/"provisioned"
    boot.rename(seed)

    def fresh():
        boot.mkdir()
        (boot/"dtb").symlink_to((seed/"dtb").resolve())
        for name in ("boot.scr","armbianEnv.txt"):
            shutil.copy2(seed/name,boot/name)
        shutil.copytree(seed/"overlay-user",boot/"overlay-user")
        reboot(True)
        assert not list(boot.glob("*-backups")) and not get()["undo"]

    def rejected_cases():
        def reject(code=409):
            before=env.read_bytes()
            post("apply",{"profile":UART_TO_PI,"token":"0"*64},code)
            assert env.read_bytes()==before and not journal.exists()
        for port_mode in ("txrx", "rtscts-ph", "rs485"):
            prepare(env,env,boot/"overlay-user","uart2","enable" if port_mode=="txrx" else "enable-"+port_mode)
            assert not preview(UART_TO_PI)["token"]
            reject()
            env.write_bytes(original)
        # Older installs can have multiple dormant blobs and no authoritative
        # selection. A missing override independently falls back to the board DT.
        try:
            for keep in ([], [saved["twi1"][0]]):
                text = replace_env_names(original.decode(), PARKED, keep)
                env.write_text(text)
                p = preview(UART_TO_PI)
                assert p["token"] and not p["issues"]
                assert p["candidate"]["pi_clocks"] == {
                    "twi0":dict(hz=DEFAULT,saved=False),
                    "twi1":dict(hz=rates["twi1"] if keep else DEFAULT,saved=False)}
            stock = original.decode().replace("overlays=pwm1-pi11", "overlays=uart2-pi-rts-cts pwm1-pi11")
            write_selection(stock, env, [name for name in tokens(stock) if name != token("uart2","rtscts")])
            assert "uart2-pi-rts-cts" in env.read_text() and preview(UART_TO_PI)["token"]
        finally:
            env.write_bytes(original)
        source=boot/"overlay-user"/"opi-uart2-header-rtscts.dtbo"
        blob=source.read_bytes()
        # Preserve the DT shape but change the immutable source overlay.
        source.write_bytes(blob+b"\x00"*4)
        try:
            assert not preview(UART_TO_PI)["token"]
            reject()
        finally:
            source.write_bytes(blob)
        file=boot/"overlay-user"/(saved["twi1"][0]+".dtbo")
        blob=file.read_bytes()
        try:
            file.unlink()
            reject(503)
            file.write_bytes(b"invalid")
            reject(503)
        finally:
            file.write_bytes(blob)
        for dts in ('&{/} { other { test-gpios=<&pio 8 8 0>; }; };',
                    '&uart2 { serial-client { compatible="test,peripheral"; }; };'):
            blob=boot/"overlay-user"/"uart-handoff-client.dtbo"
            subprocess.run(["dtc","-q","-@","-o",blob],input=('/dts-v1/;/plugin/;'+dts).encode(),check=True)
            write_selection(original.decode(),env,[*tokens(original.decode()),blob.stem])
            assert not preview(UART_TO_PI)["token"]
            reject()
            env.write_bytes(original)
            blob.unlink()

    module = SystemModule()
    menu = dict(module.get_menu_items())["Шины и контакты"]
    def urwid(to_i2c, cancel=False):
        if not to_i2c:
            forward_urwid("save")
            return
        def choose(title,items):
            if title.startswith("Шины и контакты"): return items.index("UART")
            if title.startswith("UART ·"): return items.index(UART_TO_PI_LABEL)
            assert all(f"I²C{bus[-1]} · {hz} Гц" in title for bus,hz in rates.items()),title
            assert UART_TO_PI_LABEL in title and all(a in title and b in title for a,b in PINS.values())
            return items.index("Назад" if cancel else "Сохранить для следующей загрузки")
        with patch.object(module,"show_menu",side_effect=choose), patch.object(module,"show_message"), \
             patch.object(module,"show_error",side_effect=AssertionError):
            menu()
    def native(to_i2c):
        if not to_i2c:
            forward_native("save")
        elif os.environ.get("PANEL_TEST_DIALOG"):
            dialog(helper,get,False,False,target=UART_TO_PI,owners="I²C0 и I²C1",direct=True,clocks=rates.values())
        else:
            res=subprocess.run([helper,"native"],env=os.environ|{"PANEL_GROUP":"UART","PANEL_CHOICE":UART_TO_PI,
                               "PANEL_CONFIRM":"yes"},capture_output=True,text=True,check=True)
            assert "Сохранено" in res.stdout

    frontends=[("urwid",urwid),("native",native)]
    if os.environ.get("PANEL_TEST_CHROMIUM"):
        frontends.append(("Chromium",None))
    for name,frontend in frontends:
        if boot.exists():
            boot.rename(tmp/f"previous-{name}")
        fresh()
        if name=="urwid":
            rejected_cases()
            urwid(True,cancel=True)
            assert env.read_bytes()==original and not journal.exists()
        plan=preview(UART_TO_PI)
        assert plan["transition"]==UART_TO_PI_LABEL and not plan["issues"] and plan["token"]
        assert plan["candidate"]["pi_clocks"] == {bus:dict(hz=hz,saved=False) for bus,hz in rates.items()}
        assert {r["pin"] for r in plan["changes"]}==set(PINS)
        previous=env.read_bytes()
        entries=set()
        def observe(uart):
            nonlocal previous, entries
            now=set(journal.glob("change.*"))
            entry,=now-entries
            assert (entry/"before").read_bytes()==previous and (entry/"after").read_bytes()==env.read_bytes()!=previous
            entries,previous=now,env.read_bytes()
            reboot(uart)
            assert parked(env.read_text())==(saved if uart else {})
            if not uart:
                assert set(tokens(env.read_text())) >= {n for n,_ in saved.values()}
                repeat=preview(UART_TO_PI)
                assert not repeat["changed"] and not repeat["issues"]
                post("apply",{"profile":UART_TO_PI,"token":repeat["token"]})
                assert set(journal.glob("change.*"))==entries
        if frontend:
            frontend(True)
            observe(False)
            frontend(False)
            observe(True)
        else:
            from panel_browser import check
            check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,observe=observe,reverse_uart=True)
        assert len(entries)==2
        print(f"PASS {name}: empty history, one save PI UART2 RTS/CTS → I2C0/I2C1 at {rates['twi0']}/{rates['twi1']} Hz, explicit forward save parks both rates again",flush=True)
