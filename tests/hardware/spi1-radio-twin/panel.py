"""Exercise both GUI clients and the native menu against a private Armbian boot DT.

Usage: python3 panel.py ALLWINNER_DTB_DIRECTORY ARMBIAN_GUI_CHECKOUT [PACKAGE_PREFIX]
The optional prefix is the extracted /opt/armbian-config-zero2w package directory.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

repo = Path(__file__).resolve().parents[3]
dtbs, gui = (Path(p).resolve() for p in sys.argv[1:3])
prefix = Path(sys.argv[3]).resolve() if len(sys.argv) == 4 else repo
sys.path[:0] = [str(gui), str(prefix / "share/armbian-config")]
from core import bus_panel as client
from modules.system.system_module import SystemModule
from uart_routes import read_tree
from webui_server import create_app

harness = '''#!/bin/bash
set -eu
script_dir=$PANEL_PREFIX/bin
declare -A module_options
if [[ -n $PANEL_PACKAGE ]]; then
    source "$PANEL_PREFIX/lib/armbian-config/config.system.sh"
else
    for name in devicetree_overlays sx1262_overlay spi1_panel ups_dfr0528 spi_clocks; do
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
 seed)
    module_sx1262_overlay shared
    module_spi_clocks set spi1 1 1000000
    module_spi_clocks set spi1 2 4000000
    _zero2w_overlay_prepare compose "$(_ups_dfr_boot)/armbianEnv.txt" "$PANEL_TEST/live.dtb" sx1262 '' ;;
 native)
    dialog_menu() { echo "$PANEL_CHOICE"; }
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
    def native(choice, confirm):
        subprocess.run([helper, "native"], env=os.environ | dict(PANEL_CHOICE=choice, PANEL_CONFIRM=confirm),
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
    drive([3]); assert env.read_bytes() == original
    verify_three(backend("state")["current"])
    native("single","yes"); verify_single(backend("state")["current"])
    drive([1,1]); verify_three(backend("state")["current"])
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


with tempfile.TemporaryDirectory() as temp:
    tmp = Path(temp); boot = tmp/"boot"; boot.mkdir()
    (boot/"dtb").mkdir(); (boot/"dtb/allwinner").symlink_to(dtbs)
    (boot/"armbianEnv.txt").write_text("rootdev=UUID=twin\noverlay_prefix=sun50i-h616\noverlays=i2c1-pi pwm1-pi11\n")
    (boot/"boot.scr").write_text('armbianEnv.txt overlay-user/${overlay_file}.dtbo')
    live = tmp/"live"; live.mkdir(); (live/"compatible").write_bytes(b"xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0")
    helper = tmp/"helper"; helper.write_text(harness); helper.chmod(0o755)
    os.environ.update(PANEL_PREFIX=str(prefix), PANEL_TEST=temp, PANEL_PACKAGE="yes" if len(sys.argv)==4 else "",
                      OPI_WEB_OPERATOR_TOKEN="write")
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
        check(boot, helper, tmp)
