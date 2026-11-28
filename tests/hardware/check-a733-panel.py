"""Exercise BUS002 against the distribution's actual A733 DTB with private /boot and sysfs.
Usage: python3 check-a733-panel.py ALLWINNER_DIR GUI_CHECKOUT [EXTRACTED_CONFIG_PREFIX]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

repo = Path(__file__).resolve().parents[2]
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("vendor", type=Path)
cli.add_argument("gui", type=Path)
cli.add_argument("prefix", type=Path, nargs="?")
cli.add_argument("--transition-only", action="store_true")
args = cli.parse_args()
vendor, gui = args.vendor.resolve(), args.gui.resolve()
prefix = args.prefix.resolve() if args.prefix else repo
sys.path[:0] = [str(gui), str(prefix/"share/armbian-config")]
import a733_io as io
import a733_panel
from bus_panel import live_tree
from core import bus_panel as client
from modules.system.system_module import SystemModule
from uart_routes import read_tree
from webui_server import create_app


def sysfs(dt, dest):
    for node, props in read_tree(dt).items():
        path = dest / node.lstrip("/")
        path.mkdir(exist_ok=True, parents=True)
        for key, val in props.items():
            (path/key).write_bytes(val)


def native_dialog(helper, undo):
    """Drive the actual BUS002 dialogs. Opt in with PANEL_TEST_DIALOG=1 (pexpect)."""
    import pexpect
    down = "\x1bOB"
    confirm = "\x1bOD\r"
    with pexpect.spawn(str(helper), ["dialog"], encoding="utf-8", timeout=25,
                       dimensions=(34,120), env=os.environ | {"TERM":"xterm","LC_ALL":"C.UTF-8"}) as tty:
        tty.expect_exact("40-контактная")
        if undo:
            tty.send(down*6 + "\r")
        else:
            tty.send(down + "\r")
            tty.expect_exact("CS0 (11)")
            tty.send(down*9 + "\r")
            tty.expect_exact("Предпросмотр перехода?")
            tty.expect_exact("камеру VIN и I²C2")
            tty.send(confirm)
            tty.expect_exact("Сохранить для следующей загрузки?")
            tty.expect_exact("камеру VIN и I²C2")
            tty.send(confirm)
        tty.expect_exact("Сохранено для")
        tty.send("\r")
        tty.expect(pexpect.EOF)
    assert tty.exitstatus == 0


def check_transition(tmp, helper, get, post, browser=None):
    boot = tmp / "boot"
    env = boot / "armbianEnv.txt"
    original = env.read_bytes()
    # Keep a real unrelated route, comments and ordering across both UI paths.
    env.write_bytes(original + b"# keep this assignment in place\noverlays=i2c0\n")
    enable_i2c = "a733-i2c2-400000"
    p = post("preview", {"profile":enable_i2c}, viewer=True)
    post("apply", {"profile":enable_i2c,"token":p["token"]})
    baseline = env.read_bytes()
    spi_path = io.SOC + io.ROUTES["spi3"][0]
    i2c_path = io.SOC + io.ROUTES["i2c2"][0]
    routes = {19:(i2c_path,"I²C2 SDA","SPI3 MOSI"), 23:(i2c_path,"I²C2 SCL","SPI3 CLK"),
              24:(io.CAMERA,"Камера VIN · MCLK","SPI3 CS0")}
    journal = boot / "armbianEnv.txt.a733-panel-backups"
    def history():
        return set(journal.glob("change.*"))
    initial_live = (tmp / "live").resolve()
    boot_number = 0

    def reboot(spi):
        nonlocal boot_number
        boot_number += 1
        image = tmp / "handoff.dtb"
        tree, saved = io.compose(boot, env.read_text(), image)
        io.verify(tree, saved)
        assert io.enabled(tree, io.CAMERA) == (not spi)
        assert io.enabled(tree, i2c_path) == (not spi)
        assert io.enabled(tree, spi_path) == spi
        if not spi:
            assert io.cells(tree[i2c_path]["clock-frequency"]) == [400000]
        assert io.enabled(tree, io.SOC + io.ROUTES["i2c0"][0])
        live = tmp / f"handoff-boot-{boot_number}"
        sysfs(image, live)
        (tmp / "live-next").symlink_to(live)
        (tmp / "live-next").replace(tmp / "live")
        model = get()["live"]
        pins = {row["pin"]:row["owners"] for row in model["pins"]}
        for pin, (source, old, new) in routes.items():
            assert pins[pin] == [{"path":spi_path if spi else source, "label":new if spi else old}]
        assert [(r["cs"],r["pin"]) for r in model["rows"]] == ([(0,24),(1,26)] if spi else [])

    def preview(target):
        return post("preview", {"profile":target}, viewer=True)

    def assert_one_change(prior):
        change, = history() - prior
        assert (change/"before").read_bytes() == baseline
        assert (change/"after").read_bytes() == env.read_bytes() != baseline

    plain = "a733-spi3-on"
    combined = plain + "+camera+i2c2"
    # All selection/confirmation dialogs of the GUI TUI call the real broker.
    module = SystemModule()
    menu = dict(module.get_menu_items())["Шины и контакты"]

    def tui(action):
        def select(title, items):
            if "Zero 3W" in title:
                return items.index("Откатить последнее изменение" if action == "undo" else "SPI")
            if title.startswith("SPI ·"):
                return next(i for i, item in enumerate(items) if item.startswith("SPI3 · CS0"))
            if "Конфликт" in title:
                assert all(f"Вывод {pin} (" in title for pin in routes)
                return next(i for i, item in enumerate(items) if all(n in item for n in ("камеру VIN","I²C2","SPI3")))
            assert all(n in title for n in ("камеру VIN","I²C2","SPI3 CS0","SPI3 MOSI","SPI3 CLK"))
            return items.index("Назад" if action == "cancel" else "Сохранить для следующей загрузки")
        with patch.object(module,"show_menu",side_effect=select), patch.object(module,"show_message"), \
             patch.object(module,"show_error",side_effect=AssertionError):
            menu()

    def contents():
        return {str(p.relative_to(boot)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in boot.rglob("*") if not p.is_symlink()}

    try:
        reboot(False)
        prior = history()
        untouched = contents()
        blocked = preview(plain)
        assert not blocked["token"] and blocked["alternative"]["id"] == combined
        plan = preview(combined)
        assert plan["token"] and not plan["issues"] and plan["transition"] == blocked["alternative"]["label"]
        changes = {r["pin"]:r for r in plan["changes"]}
        for pin, (source, old, new) in routes.items():
            assert changes[pin]["before"] == [{"path":source,"label":old}]
            assert changes[pin]["after"] == [{"path":spi_path,"label":new}]
        for bad in (combined + "+camera", combined + "+unknown", combined + "+spi3"):
            post("preview", {"profile":bad}, 400)
        tui("cancel")
        assert contents() == untouched
        post("apply", {"profile":combined, "token":plan["token"]}, 403, viewer=True)
        env.write_bytes(baseline+b"verbosity=7\n")
        post("apply", {"profile":combined,"token":plan["token"]}, 409)
        assert env.read_bytes() == baseline+b"verbosity=7\n" and history() == prior
        env.write_bytes(baseline)
        # An omitted, unrelated or protected owner must never cause a partial handoff.
        for suffix in ("+camera", "+i2c2", "+camera+i2c2+pinctrl-test"):
            incomplete = plain + suffix
            assert not preview(incomplete)["token"]
            post("apply", {"profile":incomplete, "token":plan["token"]}, 409)
        assert env.read_bytes() == baseline and history() == prior
        from dt_clock_overlay import tokens, write_selection
        sensor = boot/"overlay-user"/"handoff-i2c2-sensor.dtbo"
        dts = f'/dts-v1/; /plugin/; &{{{i2c_path}}} {{ sensor@42 {{ compatible="test,sensor"; reg=<0x42>; }}; }};'
        subprocess.run(["dtc","-q","-@","-o",sensor],input=dts.encode(),check=True)
        write_selection(env.read_text(), env, [*tokens(env.read_text()), sensor.stem])
        protected = env.read_bytes()
        check = preview(combined)
        assert not check["token"] and any("sensor@42" in issue for issue in check["issues"])
        post("apply", {"profile":combined,"token":plan["token"]}, 409)
        assert env.read_bytes() == protected and history() == prior
        env.write_bytes(baseline)
        # An uncatalogued claimant must block the whole transition, including the offer.
        busy = boot/"overlay-user"/"handoff-foreign.dtbo"
        dts = '/dts-v1/; /plugin/; &{/} { extra-device { test-gpios=<&pio 4 3 0>; }; };'
        subprocess.run(["dtc","-q","-@","-o",busy],input=dts.encode(),check=True)
        write_selection(env.read_text(), env, [*tokens(env.read_text()), busy.stem])
        protected = env.read_bytes()
        assert preview(plain)["alternative"] is None and not preview(combined)["token"]
        post("apply", {"profile":combined,"token":plan["token"]}, 409)
        assert env.read_bytes() == protected and history() == prior
        env.write_bytes(baseline)
        tui("save")
        assert_one_change(prior)
        repeat = preview(combined)
        assert not repeat["changed"] and not repeat["issues"]
        post("apply", {"profile":combined,"token":repeat["token"]})
        assert_one_change(prior)
        reboot(True)
        tui("undo")
        assert env.read_bytes() == baseline and len(history()-prior)==2
        reboot(False)
        print("PASS urwid: cancelled preview writes nothing; one save VIN + I2C2 → SPI3; one undo restores VIN, I2C2 at 400 kHz and exact env after simulated boots",flush=True)

        prior = history()
        for group, choice, spi in (("SPI",plain,True),("undo","undo",False)):
            if os.environ.get("PANEL_TEST_DIALOG"):
                native_dialog(helper, undo=not spi)
            else:
                cmd = subprocess.run([helper,"native"],env=os.environ | {"GROUP":group,"CHOICE":choice},
                                     check=True,capture_output=True,text=True)
                assert "Сохранено" in cmd.stdout, cmd.stdout
            if spi:
                assert_one_change(prior)
            else:
                assert env.read_bytes() == baseline
            reboot(spi)
        print("PASS native BUS002: one VIN + I2C2 / SPI3 journal entry, one undo; partial/duplicate/protected owners and stale token refused",flush=True)
        # Managed bus owners can yield a pin too, subject to their normal client checks.
        uart_id = "a733-uart2-rtscts"
        pair = preview(uart_id)["alternative"]["id"]
        assert pair == uart_id + "+i2c0"
        prior = history()
        post("apply", {"profile":pair,"token":preview(pair)["token"]})
        assert_one_change(prior)
        post("undo", {"token":get()["undo"]})
        assert env.read_bytes() == baseline
        folder = boot / "overlay-user"
        sensor = folder / "handoff-sensor.dtbo"
        dts = '/dts-v1/; /plugin/; &{/soc@3000000/twi@2510000} { sensor@42 { compatible="test,sensor"; reg=<0x42>; }; };'
        subprocess.run(["dtc","-q","-@","-o",sensor], input=dts.encode(), check=True)
        write_selection(env.read_text(), env, [*tokens(env.read_text()), sensor.stem])
        protected = env.read_bytes()
        check = preview(pair)
        assert check["token"] is None and any("sensor@42" in issue for issue in check["issues"])
        post("apply", {"profile":pair,"token":"0"*64}, 409)
        assert env.read_bytes() == protected
        env.write_bytes(baseline)
        print("PASS I²C0 → UART2 joint save/undo; declared I²C client blocks both edits",flush=True)
        if browser:
            prior = history()
            def observe(spi):
                if spi:
                    assert_one_change(prior)
                else:
                    assert env.read_bytes() == baseline and len(history()-prior) == 2
                reboot(spi)
            browser(observe)
    finally:
        env.write_bytes(original)
        (tmp/"live-next").symlink_to(initial_live)
        (tmp/"live-next").replace(tmp/"live")


def run(tmp):
    boot = tmp/"boot"
    (boot/"dtb").mkdir(parents=True)
    (boot/"dtb/allwinner").symlink_to(vendor)
    (boot/"boot.scr").write_text('armbianEnv.txt overlay-user/${overlay_file}.dtbo')
    env = boot/"armbianEnv.txt"
    env.write_text("rootdev=UUID=test\nconsole=both\noverlay_prefix=sun60i-a733\nfdtfile="+io.BASE+"\n")
    original = env.read_bytes()
    dtb = boot/"dtb"/io.BASE
    sysfs(dtb, tmp/"stock-live")
    (tmp/"live").symlink_to(tmp/"stock-live")
    helper = tmp/"helper"
    helper.write_text('''#!/bin/bash
set -eu
script_dir="$PANEL_PREFIX/bin"
declare -A module_options menu_options
if [[ -n $PANEL_PACKAGE ]]; then
    source "$PANEL_PREFIX/lib/armbian-config/config.system.sh"
else
    for m in ups_dfr0528 devicetree_overlays header_gpio a733_io spi1_panel pwm_modes sx1262_overlay; do
        source "$PANEL_PREFIX/tools/modules/system/module_$m.sh"
    done
fi
_ups_dfr_boot() { echo "$PANEL_TEST/boot"; }
_ups_dfr_dt() { echo "$PANEL_TEST/live"; }
_sx1262_class() { echo "$PANEL_TEST/class"; }
if [[ $1 == native ]]; then
    dialog_menu() { if [[ $1 == 'Шины и контакты' ]]; then echo "$GROUP"; else echo "$CHOICE"; fi; }
    dialog_yesno() { return 0; }
    dialog_msgbox() { echo "$2"; }
    module_spi1_panel select
elif [[ $1 == dialog ]]; then
    if [[ -n $PANEL_PACKAGE ]]; then
        source "$PANEL_PREFIX/lib/armbian-config/config.functions.sh"
    else
        source "$PANEL_PREFIX/tools/modules/functions/module_dialog_ui.sh"
    fi
    DIALOG=dialog BACKTITLE="Zero 3W"
    module_spi1_panel select
else
    module_spi1_panel "$@"
fi
''')
    helper.chmod(0o755)
    os.environ.update(PANEL_PREFIX=str(prefix), PANEL_PACKAGE="yes" if prefix != repo else "",
                      PANEL_TEST=str(tmp), OPI_WEB_OPERATOR_TOKEN="write")
    app = create_app(token="read")
    web = app.test_client()
    def get():
        r = web.get("/api/buses", auth=("viewer","read"))
        assert r.status_code == 200, r.json
        return r.json
    def post(action, payload, expect=200, viewer=False):
        auth = ("viewer","read") if viewer else ("operator","write")
        r = web.post("/api/buses/"+action, json=payload, auth=auth, headers={"X-OPi-Panel":"1"})
        assert r.status_code == expect, (action,payload,r.json)
        return r.json
    def preview(profile):
        return post("preview", {"profile":profile}, viewer=True)
    def apply(profile):
        r = preview(profile)
        assert r["token"] and not r["issues"], (profile, r["issues"])
        post("apply", {"profile":profile,"token":r["token"]})
        return r
    def reject(profile, pins):
        before = env.read_bytes()
        p = preview(profile)
        assert not p["token"] and p["issues"], profile
        assert all(any(f"Вывод {pin} (" in msg for msg in p["issues"]) for pin in pins), p["issues"]
        post("apply", {"profile":profile,"token":"0"*64}, 409)
        assert env.read_bytes() == before
    def undo(expected):
        post("undo", {"token":get()["undo"]})
        assert env.read_bytes() == expected
    def snapshot():
        return {p.name:(p.stat().st_mtime_ns,p.read_bytes()) for p in boot.iterdir() if p.is_file()}
    def handoff():
        browser = None
        if os.environ.get("PANEL_TEST_CHROMIUM"):
            sys.path.insert(0,str(Path(__file__).resolve().parent/"spi1-radio-twin"))
            from panel_browser import check
            def browser(observe):
                check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,board="a733", observe=observe)
        check_transition(tmp, helper, get, post, browser)

    with patch.object(client,"HELPERS",[helper]), patch.object(client,"os",SimpleNamespace(geteuid=lambda:0)):
        if args.transition_only:
            handoff()
            print("DTB SHA256",hashlib.sha256(dtb.read_bytes()).hexdigest(),flush=True)
            return
        state = get()
        live = state["live"]
        assert state["board"] == "Zero 3W" and len(live["pins"]) == 28
        assert live["pins"] == state["current"]["pins"] and not state["issues"]
        claims = {r["pin"]: {o["path"] for o in r["owners"]} for r in live["pins"]}
        assert claims[24] == {io.CAMERA} and claims[35] == {io.PIN_TEST}
        assert claims[8] == claims[10] == {io.PIN_TEST, io.SOC+"uart@2500000"}
        options = {r["pin"]:set(r["functions"]) for r in live["pins"]}
        assert options[7] == {"SPI2 CS1","PWM0-0"} and options[28] == {"S_PWM0-2"}
        post("preview", {"profile":"single"}, 400)
        post("apply", {"profile":"a733-spi2-cs0","token":"0"*64}, 403, viewer=True)
        before_files = snapshot()
        blocked = {"a733-spi3-on", "a733-uart6-txrx", "a733-uart6-rtscts", "a733-pwm8-on"}
        blocked.update(o["id"] for o in state["choices"] if o["id"].startswith("a733-spi2-cs") and o["id"].endswith("3"))
        for option in state["choices"]:
            p = preview(option["id"])
            assert bool(p["issues"]) == (option["id"] in blocked), (option["id"],p["issues"])
            assert bool(p["token"]) != bool(p["issues"])
        assert snapshot() == before_files and not (boot/"overlay-user").exists()
        print(f"PASS {len(state['choices'])} pristine board previews; {len(blocked)} expected conflicts; no boot writes", flush=True)
        reject("a733-spi3-on",[24]); reject("a733-spi2-cs03",[35])
        p = preview("a733-i2c0-400000")
        env.write_bytes(original + b"verbosity=7\n")
        post("apply", {"profile":"a733-i2c0-400000","token":p["token"]}, 409)
        assert env.read_bytes().endswith(b"verbosity=7\n")
        env.write_bytes(original)
        p = apply("a733-i2c0-400000")
        assert {r["pin"] for r in p["changes"]} == {3,5}
        assert get()["live"] == live
        nodes,_ = io.compose(boot,env.read_text(),tmp/"next.dtb")
        assert io.cells(nodes[io.SOC+io.ROUTES["i2c0"][0]]["clock-frequency"]) == [400000]
        reject("a733-spi2-cs0",[3,5]); reject("a733-uart2-rtscts",[3,5]); undo(original)
        p=apply("a733-spi2-cs012")
        assert {r["pin"] for r in p["changes"]} == {3,5,7,11,12,13}
        reject("a733-pwm0-on",[7]); reject("a733-uart2-txrx",[11,13]); undo(original)
        apply("a733-pwm9-on"); reject("a733-i2c1-100000",[40]); undo(original)
        apply("a733-pinctrl-test-release")
        released=env.read_bytes()
        apply("a733-spi2-cs03"); reject("a733-pinctrl-test-default",[35])
        reject("a733-pwm8-on",[35]); undo(released)
        apply("a733-pinctrl-test-default")
        apply("a733-camera-release")
        released=env.read_bytes()
        p=apply("a733-spi3-on")
        assert [(r["bus"],r["cs"],r["pin"],r["ceiling_hz"],r["mode"]) for r in p["candidate"]["rows"]] == [
            ("SPI3",0,24,500000,0),("SPI3",1,26,500000,0)]
        io.compose(boot,env.read_text(),tmp/"spi3.dtb")
        other_live=tmp/"booted-spi3"
        sysfs(tmp/"spi3.dtb", other_live)
        ep = tmp/"class/spidev9.1/device"
        ep.mkdir(parents=True)
        (ep/"of_node").symlink_to(other_live/(io.SOC+io.ROUTES["spi3"][0]+"/spidev@1").lstrip("/"))
        actual = a733_panel.inventory(live_tree(other_live),other_live,tmp/"class")
        assert [row["endpoint"] for row in actual["rows"]]==[None,"/dev/spidev9.1"]
        reject("a733-camera-default",[24]); reject("a733-i2c2-400000",[19,23]); undo(released)
        apply("a733-camera-default")
        print("PASS SPI2 sparse selects, SPI3 dual endpoints, camera/IRQ, I²C, UART and PWM conflicts in both directions", flush=True)
        # Both terminal frontends use the production broker operations.
        module = SystemModule()
        menu = dict(module.get_menu_items())["Шины и контакты"]
        seen = []
        def select(title, items):
            seen.append(title)
            if "Zero 3W" in title: return items.index("UART")
            if title.startswith("UART ·"): return next(i for i,item in enumerate(items) if item.startswith("UART7 TX/RX"))
            assert "PL2" in title and "PL3" in title
            return 1
        before=env.read_bytes()
        with patch.object(module,"show_menu",side_effect=select), patch.object(module,"show_message"):
            menu()
        assert len(seen)==3 and "uart7--on" in env.read_text()
        arg_env = os.environ | {"GROUP":"PWM","CHOICE":"a733-pwm22-on"}
        uart=env.read_bytes()
        subprocess.run([helper,"native"],env=arg_env,check=True,capture_output=True)
        state=get()
        owners={r["pin"]:[o["label"] for o in r["owners"]] for r in state["current"]["pins"]}
        assert owners[16]==["UART7 TX"] and owners[18]==["UART7 RX"] and owners[28]==["S_PWM0-2"]
        subprocess.run([helper,"native"],env=arg_env | {"GROUP":"undo"},check=True,capture_output=True)
        assert env.read_bytes()==uart and state["live"]==live
        apply("a733-uart7-off")
        print("PASS urwid and native menu handlers, standby UART/PWM, one-step byte-exact undo and stale apply",flush=True)
        # Existing A733IO device clocks survive a BUS002 switch and undo.
        folder=boot/"overlay-user"
        src='/dts-v1/; /plugin/; &spi2 { sensor@0 {reg=<0>;compatible="test,sensor";spi-max-frequency=<8000000>;};};'
        subprocess.run(["dtc","-q","-@","-o",folder/"sensor.v1.dtbo"],input=src.encode(),check=True)
        from dt_clock_overlay import install_blob, tokens, write_selection
        values=["2000000","2","sensor@0".encode().hex()]
        key="spi2-cs0"
        name=io.PREFIX+key+"--"+"-".join(values)
        install_blob(folder,name,io.overlay(key, values))
        install_blob(folder,io.PREFIX+"spi2--on",io.overlay("spi2",["on"]))
        write_selection(env.read_text(),env,[*tokens(env.read_text()),"sensor.v1",io.PREFIX+"spi2--on",name])
        previous=env.read_bytes()
        p=apply("a733-spi2-cs02")
        row,=p["candidate"]["rows"]
        assert (row["bus"],row["cs"],row["ceiling_hz"],row["mode"])==("SPI2",0,2000000,2)
        reject("a733-spi2-off",[])
        undo(previous)
        env.write_bytes(original)
        print("PASS renumbered spidev binding, declared SPI2 client clock/mode across CS edits and rollback",flush=True)
        handoff()
        print("DTB SHA256",hashlib.sha256(dtb.read_bytes()).hexdigest(),flush=True)


with TemporaryDirectory() as name:
    run(Path(name))
