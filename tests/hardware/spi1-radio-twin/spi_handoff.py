"""Zero 2W I²C3/I²C4 PH → shared SPI1 on a private boot tree; no device I/O."""
import hashlib
import os
import subprocess
import shutil
from unittest.mock import patch

from dt_clock_overlay import tokens, write_selection
from header_panel import SPI_TO_PH, SPI_TO_PH_LABEL
from h618_handoff import dialog
from i2c_clocks import BUSES
from modules.system.system_module import SystemModule
from spi1_radios import BUS, CLIENTS, SHARED
from spi_devices import MARKER, managed, saved_names
from uart_routes import cells, enabled, read_tree

TARGET = "shared+i2c3+i2c4"
RATES = {1:1_000_000, 2:4_000_000}
PARKED = {str(cs):hz for cs,hz in RATES.items()}
PINS = {18:("I²C3 SCL","nRF24 CE"), 24:("I²C3 SDA","SPI1 CS2"),
        23:("I²C4 SCL","SPI1 CLK"), 19:("I²C4 SDA","SPI1 MOSI")}


def check_handoff(tmp, helper, repo, app, *, reverse=False):
    boot = tmp/"boot"
    env = boot/"armbianEnv.txt"
    folder = boot/"overlay-user"
    journal = boot/"armbianEnv.txt.spi1-panel-backups"
    web = app.test_client()

    def get():
        res = web.get("/api/buses", auth=("viewer","read"))
        assert res.status_code == 200, res.json
        return res.json

    def post(action, body, status=200, *, viewer=False):
        auth = ("viewer","read") if viewer else ("operator","write")
        res = web.post("/api/buses/"+action, json=body, auth=auth, headers={"X-OPi-Panel":"1"})
        assert res.status_code == status, (body,res.json)
        return res.json

    def preview(target):
        return post("preview", {"profile":target}, viewer=True)

    def save(target):
        plan = preview(target)
        assert plan["token"] and not plan["issues"], plan["issues"]
        return post("apply", {"profile":target,"token":plan["token"]})

    def history():
        return set(journal.glob("change.*"))

    def files():
        return {p.relative_to(boot):p.read_bytes() for p in boot.rglob("*")
                if p.is_file() and p.name != "armbianEnv.txt.overlay.lock"}

    # Create the clock blobs via SPI001 and park them through the normal profile selector.
    subprocess.run([helper,"seed"], check=True,stdout=subprocess.DEVNULL)
    if not reverse:
        save("off")
        save("i2c3-ph")
        save("i2c4-ph")
        for bus,rate in (("twi3","100000"),("twi4","400000")):
            subprocess.run([helper,"clock",bus,rate],check=True,stdout=subprocess.DEVNULL)
    baseline = env.read_bytes()
    clocks = managed(tokens(env.read_text()) if reverse else saved_names(env.read_text()))
    blobs = {folder/(name+".dtbo"):(folder/(name+".dtbo")).read_bytes()
             for (bus,cs),(name,hz) in clocks.items() if bus=="spi1" and RATES.get(cs)==hz}
    assert len(blobs)==2

    def verify_model(model, shared):
        assert model["profile"] == ("shared" if shared else "off")
        by_pin = {r["pin"]:r["owners"] for r in model["pins"]}
        for pin,signals in PINS.items():
            assert [o["label"] for o in by_pin[pin]] == [signals[shared]], (pin,by_pin[pin])
        assert by_pin[32][0]["label"]=="PWM1" and by_pin[3][0]["label"]=="I²C1 SDA"
        rows = model["rows"]
        if shared:
            assert [(r["device"],r["cs"],r["pin"]) for r in rows] == [
                ("SX1262",0,40),("CC1101",1,26),("nRF24",2,24)]
            assert all(rows[cs]["requested_hz"]==rows[cs]["ceiling_hz"]==hz for cs,hz in RATES.items())
        else:
            assert not rows
        if "parked" in model:
            assert model["parked"] == ({} if shared else PARKED)

    generation = 0
    def reboot(shared):
        nonlocal generation
        generation += 1
        subprocess.run([helper,"boot-dtb"],check=True)
        tree = read_tree(tmp/"booted.dtb")
        assert enabled(tree,BUS)==shared
        assert all(p.read_bytes()==raw for p,raw in blobs.items())
        for bus,hz in (("twi3",100000),("twi4",400000)):
            path = BUSES[bus]
            assert enabled(tree,path) != shared
            if not shared and not reverse: assert cells(tree[path]["clock-frequency"]) == [hz]
        if shared:
            for cs,hz in RATES.items():
                child = tree[BUS+"/"+CLIENTS[cs][0]]
                assert cells(child[MARKER])==cells(child["spi-max-frequency"])==[hz]
            assert SHARED in tokens(env.read_text()) and not saved_names(env.read_text())
        else:
            assert managed(saved_names(env.read_text())) == clocks
        dest = tmp/f"spi1-boot-{generation}"
        for path,props in tree.items():
            node = dest/path.lstrip("/")
            node.mkdir(parents=True,exist_ok=True)
            for k,v in props.items(): (node/k).write_bytes(v)
        (tmp/"live-next").symlink_to(dest)
        (tmp/"live-next").replace(tmp/"live")
        state = get()
        for section in ("live","current"): verify_model(state[section],shared)

    if reverse:
        check_reverse(tmp, helper, app, get, post, reboot)
        print("DTB SHA256",hashlib.sha256((boot/"dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb").read_bytes()).hexdigest(),flush=True)
        return

    reboot(False)
    original_files, prior = files(), history()
    blocked = preview("shared")
    assert blocked["alternative"]["id"] == TARGET and not blocked["token"]
    plan = preview(TARGET)
    assert plan["token"] and not plan["issues"] and plan["transition"]==blocked["alternative"]["label"]
    verify_model(plan["candidate"],True)
    for incomplete in ("shared+i2c3","shared+i2c4",TARGET+"+pwm1"):
        assert not preview(incomplete)["token"]
        post("apply",{"profile":incomplete,"token":plan["token"]},409)
    post("preview",{"profile":TARGET+"+i2c3"},400)
    post("apply",{"profile":TARGET,"token":plan["token"]},403,viewer=True)
    assert files()==original_files and history()==prior

    # A peripheral control line also belongs to the profile. An unknown claimant blocks it.
    foreign = folder/"test-spi1-owner.dtbo"
    subprocess.run(["dtc","-q","-@","-o",foreign],input=b'/dts-v1/; /plugin/; &{/} { tester { test-gpios=<&pio 2 12 0>; }; };',check=True)
    write_selection(env.read_text(),env,[*tokens(env.read_text()),foreign.stem])
    obstructed = files()
    assert preview("shared")["alternative"] is None
    denied = preview(TARGET)
    assert denied["token"] is None and any("Вывод 36" in issue for issue in denied["issues"])
    post("apply",{"profile":TARGET,"token":plan["token"]},409)
    assert files()==obstructed and history()==prior
    env.write_bytes(baseline)

    # An I²C child depends on the original route and a damaged dormant clock
    # cannot be promoted. Neither condition may let the other bus be released.
    sensor = folder/"test-i2c3-sensor.dtbo"
    dts = f'/dts-v1/; /plugin/; &{{{BUSES["twi3"]}}} {{ sensor@42 {{ compatible="test,sensor"; reg=<0x42>; }}; }};'
    subprocess.run(["dtc","-q","-@","-o",sensor],input=dts.encode(),check=True)
    write_selection(env.read_text(),env,[*tokens(env.read_text()),sensor.stem])
    obstructed = files()
    assert preview("shared")["alternative"] is None
    assert any("sensor@42" in issue for issue in preview(TARGET)["issues"])
    post("apply",{"profile":TARGET,"token":plan["token"]},409)
    assert files()==obstructed and history()==prior
    env.write_bytes(baseline)
    cs2 = folder/(clocks["spi1",2][0]+".dtbo")
    cs2.write_bytes(b"invalid")
    try:
        post("apply",{"profile":TARGET,"token":plan["token"]},503)
        assert env.read_bytes()==baseline and history()==prior
    finally:
        cs2.write_bytes(blobs[cs2])

    module = SystemModule()
    menu = dict(module.get_menu_items())["Шины и контакты"]
    def urwid(action):
        def choose(title,items):
            if title.startswith("Шины и контакты"):
                return items.index("Откатить последнее изменение" if action=="undo" else "SPI1")
            if title.startswith("SPI1 ·"):
                return items.index("SX1262 + CC1101 + nRF24")
            if "Конфликт" in title:
                assert all(f"Вывод {pin} (" in title for pin in PINS)
                return next(i for i,item in enumerate(items) if "I²C3 и I²C4" in item)
            assert "I²C3 и I²C4" in title and all(str(hz)+" Гц" in title for hz in RATES.values())
            return items.index("Назад" if action=="cancel" else "Сохранить для следующей загрузки")
        with patch.object(module,"show_menu",side_effect=choose), patch.object(module,"show_message"), \
             patch.object(module,"show_error",side_effect=AssertionError):
            menu()

    def native(action):
        if os.environ.get("PANEL_TEST_DIALOG"):
            dialog(helper,get,action=="undo",False,group="SPI1",target="shared",owners="I²C3 и I²C4")
        else:
            res = subprocess.run([helper,"native"],env=os.environ | {"PANEL_GROUP":"undo" if action=="undo" else "SPI1",
                                 "PANEL_CHOICE":"shared","PANEL_CONFIRM":"yes"},text=True,capture_output=True,check=True)
            assert "Сохранено" in res.stdout

    def observe(shared):
        if shared:
            entry, = history()-prior
            assert (entry/"before").read_bytes()==baseline and (entry/"after").read_bytes()==env.read_bytes()!=baseline
        else:
            assert len(history()-prior)==2 and env.read_bytes()==baseline
        reboot(shared)

    intact = files()
    urwid("cancel")
    assert files()==intact
    for frontend in (urwid,native):
        prior=history()
        frontend("save")
        observe(True)
        repeat=preview(TARGET)
        assert not repeat["changed"] and not repeat["issues"]
        post("apply",{"profile":TARGET,"token":repeat["token"]})
        assert len(history()-prior)==1
        frontend("undo")
        observe(False)
        print(f"PASS {frontend.__name__}: I2C3/I2C4 PH → all three SPI1 clients in one journal change, CS1=1000000 and CS2=4000000 Hz; one undo restores I2C and both parked CS clocks byte-for-byte",flush=True)
    if os.environ.get("PANEL_TEST_CHROMIUM"):
        from panel_browser import check
        prior=history()
        check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,observe=observe,spi1=True)
    print("PASS separate radio child claims, partial/unknown owners, cancel, retry and viewer permissions",flush=True)
    print("DTB SHA256",hashlib.sha256((boot/"dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb").read_bytes()).hexdigest(),flush=True)

def check_reverse(tmp, helper, app, get, post, reboot):
    boot = tmp/"boot"
    env = boot/"armbianEnv.txt"
    journal = boot/"armbianEnv.txt.spi1-panel-backups"
    seed = tmp/"seeded-boot"
    boot.rename(seed)

    def fresh():
        # Provision each frontend from active files alone. No change journals.
        boot.mkdir()
        (boot/"dtb").symlink_to((seed/"dtb").resolve())
        for name in ("boot.scr","armbianEnv.txt"):
            shutil.copy2(seed/name,boot/name)
        shutil.copytree(seed/"overlay-user",boot/"overlay-user")
        reboot(True)
        assert not get()["undo"] and not list(boot.glob("*-backups"))

    def preview(key):
        return post("preview",{"profile":key},viewer=True)

    def negative_cases():
        # Both routes must be validated even if only the second has a foreign
        # provider. The damaged CS2 case also exercises verification before parking.
        before = env.read_bytes()
        extra = boot/"overlay-user/test-extra.dtbo"
        for dts in (b'/dts-v1/;/plugin/; &{/} { t { test-gpios=<&pio 7 7 0>; }; };',
                    b'/dts-v1/;/plugin/; &spi1 { sensor@3 {reg=<3>;compatible="test,extra";spi-max-frequency=<1000000>;}; };'):
            subprocess.run(["dtc","-q","-@","-o",extra],input=dts,check=True)
            write_selection(before.decode(),env,[*tokens(before.decode()),extra.stem])
            obstructed = env.read_bytes()
            p = preview(SPI_TO_PH)
            assert not p["token"] and p["issues"]
            post("apply",{"profile":SPI_TO_PH,"token":"0"*64},409)
            assert env.read_bytes()==obstructed and not journal.exists()
        env.write_bytes(before)
        extra.unlink()
        cs2 = boot/"overlay-user"/(managed(tokens(env.read_text()))["spi1",2][0]+".dtbo")
        data = cs2.read_bytes()
        try:
            cs2.write_bytes(b"broken")
            post("apply",{"profile":SPI_TO_PH,"token":"0"*64},503)
            assert env.read_bytes()==before and not journal.exists()
        finally:
            cs2.write_bytes(data)

    module = SystemModule()
    menu = dict(module.get_menu_items())["Шины и контакты"]
    def urwid(reverse, cancel=False):
        def choose(title,items):
            if title.startswith("Шины и контакты"):
                return items.index("SPI1")
            if title.startswith("SPI1 ·"):
                return items.index(SPI_TO_PH_LABEL if reverse else "SX1262 + CC1101 + nRF24")
            if "Конфликт" in title:
                assert not reverse
                return next(i for i,item in enumerate(items) if "I²C3 и I²C4" in item)
            assert "I²C3 и I²C4" in title and all(str(hz)+" Гц" in title for hz in RATES.values())
            return items.index("Назад" if cancel else "Сохранить для следующей загрузки")
        with patch.object(module,"show_menu",side_effect=choose), patch.object(module,"show_message"), \
             patch.object(module,"show_error",side_effect=AssertionError):
            menu()

    def native(reverse):
        key = SPI_TO_PH if reverse else "shared"
        if os.environ.get("PANEL_TEST_DIALOG"):
            dialog(helper,get,False,False,group="SPI1",target=key,owners="I²C3 и I²C4",direct=reverse)
        else:
            p=subprocess.run([helper,"native"],env=os.environ|{"PANEL_GROUP":"SPI1","PANEL_CHOICE":key,"PANEL_CONFIRM":"yes"},
                             check=True,capture_output=True,text=True)
            assert "Сохранено" in p.stdout

    frontends = [("urwid",urwid), ("native",native)]
    if os.environ.get("PANEL_TEST_CHROMIUM"):
        frontends.append(("Chromium",None))
    for name, frontend in frontends:
        if boot.exists():
            boot.rename(tmp/f"previous-{name}")
        fresh()
        before = env.read_bytes()
        if name=="urwid":
            negative_cases()
        p = preview(SPI_TO_PH)
        assert p["token"] and not p["issues"] and p["candidate"]["parked"] == PARKED
        assert p["candidate"]["profile"] == "off" and p["changed"]
        changes={r["pin"]:(r["before"],r["after"]) for r in p["changes"]}
        for pin,(i2c,spi) in PINS.items():
            old,new=changes[pin]
            assert [o["label"] for o in old]==[spi] and [o["label"] for o in new]==[i2c]
        if name=="urwid":
            urwid(True,cancel=True)
            assert env.read_bytes()==before and not journal.exists()
            post("apply",{"profile":SPI_TO_PH,"token":p["token"]},403,viewer=True)
            env.write_bytes(before+b"verbosity=7\n")
            post("apply",{"profile":SPI_TO_PH,"token":p["token"]},409)
            assert env.read_bytes()==before+b"verbosity=7\n" and not journal.exists()
            env.write_bytes(before)

        previous = before
        entries = set()
        def observe(shared):
            nonlocal previous, entries
            now = set(journal.glob("change.*"))
            entry, = now-entries
            assert (entry/"before").read_bytes()==previous and (entry/"after").read_bytes()==env.read_bytes()!=previous
            previous, entries = env.read_bytes(), now
            reboot(shared)
            if not shared:
                repeat = preview(SPI_TO_PH)
                assert not repeat["changed"] and not repeat["issues"]
                post("apply",{"profile":SPI_TO_PH,"token":repeat["token"]})
                assert set(journal.glob("change.*"))==entries and env.read_bytes()==previous
        if frontend:
            frontend(True)
            observe(False)
            frontend(False)  # explicit shared+i2c3+i2c4; never call undo
            observe(True)
        else:
            from panel_browser import check
            check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,observe=observe,spi1=True,reverse_spi1=True)
        assert len(entries)==2
        print(f"PASS {name}: empty history; one save shared SPI1 → I2C3-PH + I2C4-PH; CS1/CS2 parked at 1/4 MHz; explicit forward save restores both clocks without undo",flush=True)
