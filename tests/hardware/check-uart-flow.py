"""Restore CRTSCTS on a PTY using the pin groups from an actual composed Armbian DTB."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import termios
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/armbian-config"))
import a733_io
import a733_uart
import h616_uart as serial
import uart_routes


def check(family, port, dtb):
    raw = uart_routes.read_tree(dtb)
    if family == "a733":
        path = a733_io.SOC + a733_io.ROUTES[port][0]
    else:
        path = uart_routes.address(port)
    props = raw[path]
    assert props["armbian-config,rtscts"] == family.encode() + b"\0"
    assert props["uart-has-rtscts"] == b""

    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        base = root / "firmware/devicetree/base"
        node = base / path.lstrip("/")
        node.mkdir(parents=True)
        (base / "compatible").write_bytes(raw["/"]["compatible"])
        for key, data in props.items():
            (node / key).write_bytes(data)
        group, = [p for p, pr in raw.items() if pr.get("phandle") == props["pinctrl-0"]]
        mux = base / group.lstrip("/")
        mux.mkdir(parents=True)
        for key, data in raw[group].items():
            (mux / key).write_bytes(data)

        tty = "ttyS42"
        if family == "a733":
            device = root / "devices/platform/uart"
            device.mkdir(parents=True)
            (device / "driver").mkdir()
            (device / "of_node").symlink_to(node)
            ctl = root / "class/tty" / tty
            ctl.mkdir(parents=True)
            (ctl / "device").symlink_to(device)
            identify = a733_uart.identify
            assert identify(tty, root) == (port, node)
            stack.enter_context(patch.object(a733_uart, "identify", lambda name: identify(name, root)))
            helper, restore = a733_uart, a733_uart.restore
        else:
            stack.enter_context(patch.object(serial, "ports", return_value={tty: node}))
            helper, restore = serial, serial.restore_profile

        master, slave = os.openpty()
        stack.callback(os.close, master)
        stack.callback(os.close, slave)
        stack.enter_context(patch.object(serial, "BACKUPS", root / "backups"))
        stack.enter_context(patch.object(helper, "PROFILES", root / "profiles"))
        stack.enter_context(patch.object(serial, "busy", return_value=""))
        stack.enter_context(patch.object(serial, "reserved", return_value=""))
        real_open = os.open

        def open_device(file, *args, **kwargs):
            if file == "/dev/" + tty:
                return os.dup(slave)
            return real_open(file, *args, **kwargs)

        stack.enter_context(patch.object(os, "open", side_effect=open_device))
        before = serial.fields(termios.tcgetattr(slave), True)
        assert not before[0] & termios.CRTSCTS
        for saved in (False, True):
            if saved:
                serial.save(helper.PROFILES / (port + ".json"),
                            serial.profile_record(port, 57600, 8, "none", "1"))
            expected = serial.framing(57600, 8, "none", "1") if saved else before.copy()
            expected[0] |= termios.CRTSCTS
            restore(tty)
            assert serial.fields(termios.tcgetattr(slave), True) == expected
            serial.configure(tty, node, "rollback", label=port)
            assert serial.fields(termios.tcgetattr(slave), True) == before

        pins = (mux / "pins").read_bytes().rstrip(b"\0").split(b"\0")
        assert len(pins) == 4
        (mux / "pins").write_bytes(b"\0".join(pins[:2]) + b"\0")
        if family == "a733":
            assert identify(tty, root) is None
            restore(tty)
        else:
            try:
                restore(tty)
            except ValueError as err:
                assert "header route" in str(err)
            else:
                raise AssertionError("RTS/CTS enabled without four header pins")
        assert serial.fields(termios.tcgetattr(slave), True) == before
        print(f"PASS {family} {port}: four pads, CRTSCTS readback, saved/default framing and rollback")


if __name__ == "__main__":
    check(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
