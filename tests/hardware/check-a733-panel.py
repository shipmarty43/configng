"""Exercise BUS002 against the distribution's actual A733 DTB with private /boot and sysfs.
Usage: python3 check-a733-panel.py ALLWINNER_DIR GUI_CHECKOUT [EXTRACTED_CONFIG_PREFIX]
"""
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
vendor, gui = (Path(s).resolve() for s in sys.argv[1:3])
prefix = Path(sys.argv[3]).resolve() if len(sys.argv) == 4 else repo
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


def run(tmp):
    boot = tmp/"boot"
    (boot/"dtb").mkdir(parents=True)
    (boot/"dtb/allwinner").symlink_to(vendor)
    (boot/"boot.scr").write_text('armbianEnv.txt overlay-user/${overlay_file}.dtbo')
    env = boot/"armbianEnv.txt"
    env.write_text("rootdev=UUID=test\nconsole=both\noverlay_prefix=sun60i-a733\nfdtfile="+io.BASE+"\n")
    original = env.read_bytes()
    dtb = boot/"dtb"/io.BASE
    sysfs(dtb, tmp/"live")
    helper = tmp/"helper"
    helper.write_text('''#!/bin/bash
set -eu
script_dir="$PANEL_PREFIX/bin"
declare -A module_options
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
    with patch.object(client,"HELPERS",[helper]), patch.object(client,"os",SimpleNamespace(geteuid=lambda:0)):
        state = get()
        live = state["live"]
        assert state["board"] == "Zero 3W" and len(live["pins"]) == 28
        assert live["pins"] == state["current"]["pins"] and not state["issues"]
        claims = {r["pin"]: {o["path"] for o in r["owners"]} for r in live["pins"]}
        assert claims[24] == {io.CAMERA} and claims[35] == {io.PIN_TEST}
        assert claims[8] == claims[10] == {io.PIN_TEST, io.SOC+"uart@2500000"}
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
        if os.environ.get("PANEL_TEST_CHROMIUM"):
            sys.path.insert(0,str(Path(__file__).resolve().parent/"spi1-radio-twin"))
            from panel_browser import check
            check(app,os.environ["PANEL_TEST_CHROMIUM"],tmp,board="a733")
        print("DTB SHA256",hashlib.sha256(dtb.read_bytes()).hexdigest(),flush=True)


with TemporaryDirectory() as name:
    run(Path(name))
