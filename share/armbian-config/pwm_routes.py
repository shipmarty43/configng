"""Physical 40-pin PWM routes for the Zero 2W Armbian DT."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

import console_tty
from dt_clock_overlay import install_blob, tokens, write_selection
from uart_routes import PIO, cells, enabled, owners, read_tree, strings

# Board header numbering; the two pins in each row are alternatives.
PINS = {1: {"PI11": 32, "PH3": 13}, 2: {"PI12": 33, "PH2": 11},
        3: {"PI13": 7, "PH0": 8}, 4: {"PI14": 16, "PH1": 10}}
CTRL = "/soc/pwm@300a000"
UART0 = "/soc/serial@5000000"
RELEASE = "opi-pwm-release-uart0"


def channel_node(n):
    return f"/soc/pwm{n}@0300a000"


def group_name(n, pin):
    return f"pwm{n}-{pin[:2].lower()}-pin"


def overlay(n, pin):
    return f"pwm{n}-{pin.lower()}"


def routed_pin(nodes, n):
    path = channel_node(n)
    if not enabled(nodes, path) or not nodes[path].get("pinctrl-0"):
        return None
    refs = nodes[path]["pinctrl-0"]
    for pin in PINS[n]:
        group = nodes.get(f"{PIO}/{group_name(n, pin)}", {})
        if (group.get("phandle") == refs and strings(group.get("pins", b"")) == [pin]
                and strings(group.get("function", b"")) == [f"pwm{n}"]):
            return pin
    return "external"


def stock(text):
    values = re.findall(r"^overlays=([^\n]*)$", text, re.M)
    if len(values) > 1:
        raise ValueError("Duplicate overlays entry")
    return values[0].split() if values else []


def edit(text, n, pin):
    selected = stock(text)
    choices = {overlay(n, p) for p in PINS[n]}
    updated = []
    for token in selected:
        if token not in choices:
            updated.append(token)
        elif pin and overlay(n, pin) not in updated:
            updated.append(overlay(n, pin))
    if pin and overlay(n, pin) not in updated:
        updated.append(overlay(n, pin))
    if selected == updated:
        return text
    value = "overlays=" + " ".join(updated)
    if re.search(r"^overlays=", text, re.M):
        return re.sub(r"^overlays=.*$", lambda _: value, text, flags=re.M)
    return text + ("" if text.endswith("\n") else "\n") + value + "\n"


def release_blob():
    source = f'/dts-v1/; /plugin/; &{{{UART0}}} {{ status = "disabled"; }};'
    return subprocess.check_output(["dtc", "-q", "-I", "dts", "-O", "dtb"], input=source.encode())


def check_console(text, boot):
    env = console_tty.values(text)
    for key in ("extraargs", "extraboardargs"):
        if any(re.match(r"(console|earlycon|earlyprintk|kgdboc)(?:=|$)", word)
               for word in env.get(key, "").split()):
            raise ValueError("Custom console arguments prevent releasing UART0")
    selected, _ = console_tty.selection(env, console_tty.supported_boot(boot))
    if "ttyS0" in selected:
        raise ValueError("UART0 is selected as next-boot console; use CTTY01 first")


def release_live_check():
    import h616_uart as uart
    actual = [name for name, node in uart.ports().items() if node.name == "serial@5000000"]
    for name in actual or ["ttyS0"]:
        reason = uart.busy(name) or uart.reserved(name)
        if reason:
            raise ValueError(f"UART0 is reserved on {name}: {reason}")


def verify(nodes, text, boot):
    if not {"xunlong,orangepi-zero2w", "allwinner,sun50i-h618"} <= set(strings(nodes["/"]["compatible"])):
        raise ValueError("Expected Zero 2W DT")
    selected = stock(text)
    was_released = RELEASE in tokens((boot/"armbianEnv.txt").read_text())
    released = RELEASE in tokens(text)
    if released:
        if not was_released:
            release_live_check()
        check_console(text, boot)
        if ((boot/"overlay-user"/(RELEASE+".dtbo")).read_bytes() != release_blob() or
                enabled(nodes, UART0) or strings(nodes["/aliases"].get("serial0", b"")) != [UART0]):
            raise ValueError("Unexpected UART0 release overlay, alias or final status")
    claims = owners(nodes)
    if was_released and not released and enabled(nodes, UART0):
        for pin in ("PH0", "PH1"):
            foreign = claims.get(pin, set()) - {UART0}
            if foreign:
                raise ValueError(f"Cannot restore UART0: {pin} is owned by " + ", ".join(sorted(foreign)))
    for n, pins in PINS.items():
        mapping = {overlay(n, pin): pin for pin in pins}
        targets = [mapping[name] for name in selected if name in mapping]
        if not targets:
            continue
        if len(targets) != 1:
            raise ValueError(f"Select exactly one output pin for PWM{n}")
        pin = targets[0]
        path = channel_node(n)
        children = cells(nodes[CTRL].get("sunxi-pwms", b""))
        if (not enabled(nodes, CTRL) or "allwinner,sun50i-h616-pwm" not in strings(nodes[CTRL]["compatible"])
                or len(children) != 6 or nodes[path].get("phandle") != children[n].to_bytes(4, "big")
                or strings(nodes[path].get("pinctrl-names", b"")) != ["default"]
                or strings(nodes[path]["compatible"]) != [f"allwinner,sunxi-pwm{n}"]
                or routed_pin(nodes, n) != pin or cells(nodes[path].get("bind_pwm", b"")) not in ([], [255])
                or cells(nodes[path].get("clk_bypass_output", b"")) not in ([], [0])):
            raise ValueError(f"Expected independent PWM{n} routed to {pin}")
        conflict = claims.get(pin, set()) - {path}
        if conflict:
            raise ValueError(f"PWM{n}: {pin} is claimed by " + ", ".join(sorted(conflict)))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    cmds_pins = commands.add_parser("pins")
    cmds_pins.add_argument("channel", type=int, choices=PINS)
    for action in ("list", "verify", "inactive"):
        cmd = commands.add_parser(action)
        cmd.add_argument("dtb", type=Path)
        if action == "inactive":
            cmd.add_argument("channel", type=int, choices=PINS)
        elif action == "verify":
            cmd.add_argument("env", type=Path)
            cmd.add_argument("boot", type=Path)
    for action in ("prepare", "uart0"):
        cmd = commands.add_parser(action)
        cmd.add_argument("before", type=Path)
        cmd.add_argument("after", type=Path)
        if action == "prepare":
            cmd.add_argument("channel", type=int, choices=PINS)
            cmd.add_argument("pin")
        else:
            cmd.add_argument("boot", type=Path)
            cmd.add_argument("mode", choices=("release", "restore"))
    args = cli.parse_args()
    if args.action == "pins":
        for pin, nr in PINS[args.channel].items():
            print(f"{pin}\tPhysical {nr}")
    elif args.action == "prepare":
        pin = args.pin.upper()
        if pin != "OFF" and pin not in PINS[args.channel]:
            raise ValueError(f"Expected {' or '.join(PINS[args.channel])} or off")
        args.after.write_text(edit(args.before.read_text(), args.channel, None if pin == "OFF" else pin))
    elif args.action == "uart0":
        text = args.before.read_text()
        names = tokens(text)
        if args.mode == "release":
            check_console(text, args.boot)
            install_blob(args.boot/"overlay-user", RELEASE, release_blob())
            if RELEASE not in names:
                names.append(RELEASE)
        else:
            names = [n for n in names if n != RELEASE]
        write_selection(text, args.after, names)
    else:
        nodes = read_tree(args.dtb)
        if args.action == "verify":
            verify(nodes, args.env.read_text(), args.boot)
        elif args.action == "inactive":
            if routed_pin(nodes, args.channel):
                raise ValueError("Another overlay provides this PWM route; resolve it in its owner first")
        else:
            for n, pins in PINS.items():
                pin = routed_pin(nodes, n)
                label = "unrouted" if pin is None else "external route" if pin == "external" else f"{pin}, pin {pins[pin]}"
                print(f"pwm{n}\tNext boot: {label}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
