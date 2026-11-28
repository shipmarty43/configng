"""Exercise both GUI clients and the native menu against a private Armbian boot DT.

Usage: python3 panel.py ALLWINNER_DTB_DIRECTORY ARMBIAN_GUI_CHECKOUT [PACKAGE_PREFIX]
The optional prefix is the extracted /opt/armbian-config-zero2w package directory.
"""
import argparse
import fcntl
import hashlib
import json
import os
import struct
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

repo = Path(__file__).resolve().parents[3]
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("dtbs", type=Path)
cli.add_argument("gui", type=Path)
cli.add_argument("prefix", type=Path, nargs="?")
g = cli.add_mutually_exclusive_group()
g.add_argument("--handoff-only", action="store_true")
g.add_argument("--uart-to-pi-only", action="store_true")
g.add_argument("--spi-handoff-only", action="store_true")
g.add_argument("--spi-to-ph-only", action="store_true")
args = cli.parse_args()
dtbs, gui = args.dtbs.resolve(), args.gui.resolve()
prefix = args.prefix.resolve() if args.prefix else repo
sys.path[:0] = [str(gui), str(prefix / "share/armbian-config")]
from core import bus_panel as client
from modules.system.system_module import SystemModule
from uart_routes import read_tree
import header_panel
from header_gpio import MAIN_2W
from header_gpio_live import Chip, CHIP_INFO, LINE_INFO, USED
from webui_server import create_app

harness = '''#!/bin/bash
set -eu
script_dir=$PANEL_PREFIX/bin
declare -A module_options menu_options
if [[ -n $PANEL_PACKAGE ]]; then
    source "$PANEL_PREFIX/lib/armbian-config/config.system.sh"
else
    for name in devicetree_overlays sx1262_overlay spi1_panel ups_dfr0528 spi_clocks i2c_clocks h616_uart header_gpio a733_io; do
        source "$PANEL_PREFIX/tools/modules/system/module_$name.sh"
    done
fi
_ups_dfr_boot() { echo "$PANEL_TEST/boot"; }
_ups_dfr_dt() { echo "$PANEL_TEST/live"; }
_sx1262_class() { echo "$PANEL_TEST/class"; }
_panel_locks() { echo "$PANEL_TEST/locks"; }
mv() {
    if [[ -e $PANEL_TEST/interrupt && ${!#} == "$PANEL_TEST/boot/armbianEnv.txt" ]]; then
        echo 'simulated failure before atomic rename' >&2; return 1
    fi
    command mv "$@"
}
case "$1" in
 boot-dtb) _zero2w_overlay_prepare compose "$PANEL_TEST/boot/armbianEnv.txt" "$PANEL_TEST/booted.dtb" spi1-panel '' ;;
 clock) shift; module_i2c_clocks set "$@" ;;
 dialog)
    if [[ -n $PANEL_PACKAGE ]]; then
        source "$PANEL_PREFIX/lib/armbian-config/config.functions.sh"
    else
        source "$PANEL_PREFIX/tools/modules/functions/module_dialog_ui.sh"
    fi
    DIALOG=dialog BACKTITLE="Zero 2W twin"
    module_spi1_panel select ;;
 seed)
    module_sx1262_overlay shared
    module_spi_clocks set spi1 1 1000000
    module_spi_clocks set spi1 2 4000000
    _zero2w_overlay_prepare compose "$(_ups_dfr_boot)/armbianEnv.txt" "$PANEL_TEST/live.dtb" sx1262 '' ;;
 native)
    dialog_menu() {
        if [[ $1 == 'Шины и контакты' ]]; then echo "$PANEL_GROUP"; else echo "$PANEL_CHOICE"; fi
    }
    dialog_yesno() { [[ "$PANEL_CONFIRM" == yes ]]; }
    dialog_msgbox() { echo "$2"; }
    module_spi1_panel select ;;
 *) module_spi1_panel "$@" ;;
esac
'''


def check(boot, helper, tmp):
    env = boot / "armbianEnv.txt"
    original = env.read_bytes()
    def snapshot():
        return {p.relative_to(boot): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).digest())
                for p in boot.rglob("*") if p.is_file()}
    def backend(*args):
        return json.loads(subprocess.check_output([helper, *args], text=True))
    def native(choice, confirm, group="SPI1"):
        subprocess.run([helper, "native"], env=os.environ | dict(PANEL_CHOICE=choice, PANEL_CONFIRM=confirm, PANEL_GROUP=group),
                       check=True, capture_output=True)
    def post(action, body, user="operator", extra=None):
        return web.post("/api/buses/" + action, auth=(user, "write" if user=="operator" else "read"),
                        headers={"X-OPi-Panel":"1"} | (extra or {}), json=body)
    def verify_three(state):
        assert state["profile"] == "shared"
        assert [(x["device"], x["cs"], x["pin"]) for x in state["rows"]] == [
            ("SX1262",0,40), ("CC1101",1,26), ("nRF24",2,24)]
        assert [x["requested_hz"] for x in state["rows"][1:]] == [1_000_000, 4_000_000]
        assert [x["ceiling_hz"] for x in state["rows"][1:]] == [1_000_000, 4_000_000]
    def verify_single(state):
        assert state["profile"] == "single" and [x["cs"] for x in state["rows"]] == [0]
        assert state["parked"] == {"1":1_000_000,"2":4_000_000}
    web = create_app(token="read").test_client()
    assert web.get("/buses").status_code == 401
    assert b'id="apply"' not in web.get("/buses",auth=("viewer","read")).data
    assert b'id="apply"' in web.get("/buses",auth=("operator","write")).data
    assert post("undo", {"token":"a"*64}, user="viewer").status_code == 403
    assert post("apply", {"token":"a"*64,"profile":"single"}, extra={"Origin":"https://other.invalid"}).status_code == 403
    assert web.post("/api/buses/undo",json={},auth=("operator","write")).status_code == 400
    assert post("preview",{"profile":"../../boot"}).status_code == 400
    assert post("undo",{"token":["bad"]}).status_code == 400
    before = snapshot()
    state = backend("state"); verify_three(state["current"]); verify_three(state["live"])
    assert [r["endpoint"] for r in state["live"]["rows"]] == ["/dev/spidev7."+str(i) for i in range(3)]
    assert state["live"]["rows"][1]["lock"] == f"PID {os.getpid()}"
    assert state["live"]["rows"][2]["lock"] == "свободна"
    preview = post("preview", {"profile":"single"}, user="viewer").json
    verify_single(preview["candidate"])
    native("single","no")
    assert before == snapshot()
    print("PASS immutable preview, cancel, renumbered live devices and per-CS owner", flush=True)

    # A competing manual edit after preview must survive an attempted apply.
    env.write_bytes(original + b"verbosity=7\n")
    assert post("apply", {"profile":"single","token":preview["token"]}).status_code == 409
    assert env.read_bytes() == original + b"verbosity=7\n"
    env.write_bytes(original)
    (tmp/"interrupt").touch()
    response = post("apply", {"profile":"single","token":preview["token"]})
    assert response.status_code == 503, response.json
    assert env.read_bytes() == original
    (tmp/"interrupt").unlink()
    assert post("apply", {"profile":"single","token":preview["token"]}).status_code == 200
    state = backend("state"); verify_single(state["current"]); verify_three(state["live"])
    assert state["undo"] and b"overlays=i2c1-pi pwm1-pi11\n" in env.read_bytes()
    print("PASS Web shared → single, pre-rename failure/retry and stale apply", flush=True)

    # Choose one-step undo in the GUI TUI. It must restore the exact initial file.
    module = SystemModule()
    action = dict(module.get_menu_items())["Шины и контакты"]
    def drive(choices):
        replies = iter(choices)
        with patch.object(module,"show_menu",side_effect=lambda title,options: next(replies)), \
             patch.object(module,"show_message"), patch.object(module,"show_error",side_effect=AssertionError):
            action()
        assert list(replies) == []
    drive([5]); assert env.read_bytes() == original
    verify_three(backend("state")["current"])
    native("single","yes"); verify_single(backend("state")["current"])
    drive([1,1,1]); verify_three(backend("state")["current"])
    print("PASS native TUI → single, GUI TUI one-step undo and explicit shared restore", flush=True)

    state = backend("state")
    env.write_bytes(env.read_bytes() + b"manual=keep\n")
    assert post("undo", {"token":state["undo"]}).status_code == 409
    assert env.read_bytes().endswith(b"manual=keep\n")
    env.write_bytes(env.read_bytes().removesuffix(b"manual=keep\n"))
    assert post("undo", {"token":state["undo"]}).status_code == 200
    verify_single(backend("state")["current"])
    # Reordering keys during boot still permits undo; an actual value change never does.
    env.write_bytes(b"".join(reversed(env.read_bytes().splitlines(keepends=True))))
    state = backend("state")
    assert post("undo", {"token":state["undo"]}).status_code == 200
    verify_three(backend("state")["current"])
    p = post("preview", {"profile":"off"}).json
    assert p["candidate"]["parked"] == {"1":1_000_000,"2":4_000_000}
    assert post("apply", {"profile":"off","token":p["token"]}).status_code == 200
    q = post("preview", {"profile":"shared"}).json; verify_three(q["candidate"])
    clock = next((boot/"overlay-user").glob("opi-sclk-spi1-cs2-*.dtbo"))
    data = clock.read_bytes(); clock.write_bytes(b"broken")
    keep = env.read_bytes(); assert post("apply", {"profile":"shared","token":q["token"]}).status_code >= 400
    assert env.read_bytes() == keep; clock.write_bytes(data)
    assert post("apply", {"profile":"shared","token":q["token"]}).status_code == 200
    assert not post("preview", {"profile":"shared"}).json["changed"]
    print("PASS one-click Web undo, external edits, reordered boot, off and damaged clock blob", flush=True)

    # Include the actual DFR0528 overlay, used by the I²C guard and pin labels.
    dfr = "zero2w-dfr0528"
    subprocess.run(["dtc","-q","-@","-o",boot/"overlay-user"/(dfr+".dtbo"),
                    repo/"hardware/dfrobot-ups/zero2w-dfr0528.dts"], check=True)
    env.write_text(env.read_text().replace("user_overlays=", "user_overlays="+dfr+" "))
    baseline = env.read_bytes()
    def preview(target):
        resp = post("preview", {"profile":target}, user="viewer")
        assert resp.status_code == 200, (target, resp.json)
        return resp.json
    def save(target):
        plan = preview(target)
        assert plan["changed"] and not plan["issues"] and plan["token"], (target, plan["issues"])
        resp = post("apply", {"profile":target,"token":plan["token"]})
        assert resp.status_code == 200, (target, resp.json)
        return plan
    def deny(target, pins, *labels):
        untouched = snapshot()
        plan = preview(target)
        assert plan["token"] is None, target
        issues = " ".join(plan["issues"])
        assert all(f"Вывод {p} (" in issues for p in pins) and all(label in issues for label in labels), issues
        assert snapshot() == untouched
        rejected = post("apply", {"profile":target,"token":"0"*64})
        assert rejected.status_code == 409, (target,rejected.json)
        assert env.read_bytes() == baseline
        return plan
    def undo_to(expected):
        state = backend("state")
        assert post("undo", {"token":state["undo"]}).status_code == 200
        assert env.read_bytes() == expected
    def owners(state, pin):
        return [o["label"] for row in state["pins"] if row["pin"]==pin for o in row["owners"]]
    state = backend("state")
    assert len(state["live"]["pins"]) == len(state["current"]["pins"]) == 28
    assert owners(state["live"],3) == ["I²C1 SDA"] and owners(state["current"],3)==["I²C1 SDA · DFR0528"]
    assert owners(state["current"],8) == ["UART0 TX"] and owners(state["current"],32) == ["PWM1"]
    assert owners(state["current"],24) == ["SPI1 CS2"]
    seen = []
    def ioctl(fd, op, buf):
        if op == CHIP_INFO:
            struct.pack_into("=I", buf, 64, 288)
            return
        assert op == LINE_INFO
        offset, = struct.unpack_from("=I", buf, 64)
        seen.append(offset)
        if offset == 8 * 32 + 7:
            buf[32:37] = b"meter"
            struct.pack_into("=Q", buf, 72, USED)
    with patch.object(header_panel.gpio, "discover", return_value={MAIN_2W:Chip(-1,ioctl)}):
        lines = state["live"]["pins"]
        assert header_panel.gpio_consumers(lines,tmp/"firmware/devicetree/base",tmp,tmp)
        assert len(set(seen)) == 28 and next(r for r in lines if r["pin"]==5)["gpio_consumer"] == "meter"
        next(r for r in lines if r["pin"]==5).pop("gpio_consumer")
    # Check the full pin list and both colliding signals (including HAT sidebands).
    deny("uart2-rtscts",[3,5],"CTS","RTS","DFR0528")
    deny("uart3-rtscts",[32],"PWM1","UART3 RTS")
    deny("uart2-txrx-ph",[23,24],"SPI1","UART2")
    deny("uart2-rtscts-ph",[19,21,23,24],"SPI1","UART2")
    deny("i2c3-ph",[18,24],"nRF24 CE","SPI1 CS2","I²C3")
    deny("pwm3-ph0",[8],"PWM3","UART0 TX")
    deny("i2c1-off",[],"ups@10")
    print("PASS I²C/UART/PWM/SPI conflicts, all physical pins and both owners, DFR0528 protected",flush=True)
    for target, expected in (("i2c2-ph",{11,13}),("uart4-txrx",{7,16}),("pwm1-ph3",{13,32})):
        prior = snapshot()
        plan = preview(target)
        assert {r["pin"] for r in plan["changes"]} == expected
        assert prior == snapshot()
        save(target)
        now = backend("state")
        assert now["current"]["pins"] == plan["candidate"]["pins"] and now["live"] == state["live"]
        verify_three(now["current"])
        undo_to(baseline)
    # Same I²C controller, different pads; undo after Armbian reorders the env.
    save("i2c2-ph")
    plan = save("i2c2-pi"); assert {r["pin"] for r in plan["changes"]} == {11,13,27,28}
    env.write_bytes(b"".join(reversed(env.read_bytes().splitlines(keepends=True))))
    undo_token = backend("state")["undo"]; assert post("undo",{"token":undo_token}).status_code == 200
    assert owners(backend("state")["current"],11) == ["I²C2 SCL"]
    save("i2c2-off"); assert not owners(backend("state")["current"],11)
    print("PASS I²C bank switch/off, UART TX/RX, PWM move, byte-exact and reordered undo; live DT fixed",flush=True)
    # Drive both terminal entry points using their real labels and the same helper.
    native("uart5-txrx","yes",group="UART")
    captured=[]
    def navigate(title, options):
        captured.append(title)
        if title.startswith("Шины и контакты"): return options.index("I²C")
        if title.startswith("I²C"): return next(i for i,o in enumerate(options) if o.startswith("I2C2 · PH"))
        assert "Конфликт" in title and "UART5" in title and "Вывод 13" in title
        assert "UART5" in options[1] and "I2C2" in options[1]
        return 0
    with patch.object(module,"show_menu",side_effect=navigate), patch.object(module,"show_error",side_effect=AssertionError):
        action()
    assert len(captured)==3
    assert owners(backend("state")["current"],11)==["UART5 TX"]
    native("undo","yes",group="undo")
    assert not owners(backend("state")["current"],11)
    print("PASS native UART selection/one-step undo and TUI I²C conflict preview",flush=True)
    save("off")
    save("uart2-txrx-ph")
    baseline = env.read_bytes()
    assert not preview("uart2-txrx-ph")["changed"]
    deny("shared", [23,24], "UART2 TX","SPI1 CS2")
    denied = preview("single")
    assert not denied["token"] and any("SPI1 CLK" in issue for issue in denied["issues"])
    save("uart2-off")
    save("shared")
    verify_three(backend("state")["current"])
    print("PASS reverse conflict from UART2 PH to SPI and restored CS1/CS2 clocks",flush=True)


with tempfile.TemporaryDirectory() as temp:
    tmp = Path(temp); boot = tmp/"boot"; boot.mkdir()
    (boot/"dtb").mkdir(); (boot/"dtb/allwinner").symlink_to(dtbs)
    (boot/"armbianEnv.txt").write_text("rootdev=UUID=twin\noverlay_prefix=sun50i-h616\noverlays=i2c1-pi pwm1-pi11\n")
    (boot/"boot.scr").write_text('armbianEnv.txt overlay-user/${overlay_file}.dtbo')
    live = tmp/"initial-live"; live.mkdir(); (tmp/"live").symlink_to(live); (live/"compatible").write_bytes(b"xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0")
    helper = tmp/"helper"; helper.write_text(harness); helper.chmod(0o755)
    os.environ.update(PANEL_PREFIX=str(prefix), PANEL_TEST=temp, PANEL_PACKAGE="yes" if args.prefix else "",
                      OPI_WEB_OPERATOR_TOKEN="write")
    if args.handoff_only or args.uart_to_pi_only or args.spi_handoff_only or args.spi_to_ph_only:
        with patch.object(client,"HELPERS",[helper]), patch.object(client,"os",SimpleNamespace(geteuid=lambda:0)):
            app = create_app(token="read")
            if args.handoff_only or args.uart_to_pi_only:
                from h618_handoff import check_handoff
                check_handoff(tmp, helper, repo, app, reverse=args.uart_to_pi_only)
            else:
                from spi_handoff import check_handoff
                check_handoff(tmp, helper, repo, app, reverse=args.spi_to_ph_only)
        sys.exit(0)
    subprocess.run([helper, "seed"], check=True, stdout=subprocess.DEVNULL)
    for node, props in read_tree(tmp/"live.dtb").items():
        node_dir = live/node.lstrip("/")
        node_dir.mkdir(exist_ok=True)
        for name, data in props.items():
            (node_dir/name).write_bytes(data)
    locks = tmp/"locks"; locks.mkdir()
    for idx, (child, lock) in enumerate(zip(["radio@0","cc1101@1","nrf24@2"],
                                            ["opi-radio.lock","opi-spi1-cs1.lock","opi-spi1-cs2.lock"])):
        dev = tmp/f"class/spidev7.{idx}/device"; dev.mkdir(parents=True)
        (dev/"of_node").symlink_to(live/"soc/spi@5011000"/child); (locks/lock).touch()
    with (locks/"opi-spi1-cs1.lock").open() as held, patch.object(client,"HELPERS",[helper]), \
         patch.object(client,"os",SimpleNamespace(geteuid=lambda:0, environ=os.environ)):
        fcntl.flock(held, fcntl.LOCK_EX)
        if os.environ.get("PANEL_TEST_CHROMIUM"):
            from panel_browser import check as check_browser
            check_browser(create_app(token="read"), os.environ["PANEL_TEST_CHROMIUM"], tmp)
        check(boot, helper, tmp)
