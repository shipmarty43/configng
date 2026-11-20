"""Run two temporary native Meshtastic nodes in a private network namespace."""
from contextlib import ExitStack, closing
import os
from pathlib import Path
from queue import Empty, Queue
import secrets
import socket
import subprocess
import tempfile
import time

from sim_client import connect_simulator
from pubsub import pub


def start_node(stack, root, index, prepare_region=False):
    port = 14403 + index
    directory = root / str(index)
    directory.mkdir(exist_ok=True)
    config = directory / "config.yaml"
    config.write_text(
        "Lora:\n  Module: sim\nConfig:\n  EnableUDP: true\n"
        f'General:\n  MACAddress: "02:00:22:33:44:0{index + 1}"\n'
    )
    if prepare_region:
        from sim_region import prepare
        prepare(directory, config, port)
    log = stack.enter_context((directory / "daemon.log").open("w+"))
    process = subprocess.Popen(
        ["/opt/opi-mesh/meshtasticd", "--config", str(config), "--port", str(port),
         "--fsdir", str(directory)], stdout=log, stderr=subprocess.STDOUT, cwd=directory)

    def stop():
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    stack.callback(stop)
    deadline = time.monotonic() + 15
    while process.poll() is None and time.monotonic() < deadline:
        try:
            client = connect_simulator(port, 7)
        except ConnectionRefusedError:
            time.sleep(0.2)
            continue
        return stack.enter_context(closing(client))
    raise RuntimeError(f"Simulator {index} failed to start (exit {process.poll()})")


def check():
    if (os.readlink("/proc/self/ns/net") == os.readlink("/proc/1/ns/net")
            or {name for _, name in socket.if_nameindex()} != {"lo"}):
        raise SystemExit("Run in a private loopback-only namespace")
    if os.path.exists("/dev/spidev1.0") or os.path.exists("/dev/gpiochip0"):
        raise SystemExit("Run with PrivateDevices=yes")
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        first, second = [start_node(stack, Path(directory), index) for index in range(2)]
        received = Queue()

        def message(packet, interface):
            received.put((interface, packet.get("from"), packet.get("decoded", {}).get("text")))

        pub.subscribe(message, "meshtastic.receive.text")
        stack.callback(pub.unsubscribe, message, "meshtastic.receive.text")
        for source, target in ((first, second), (second, first)):
            payload = "opi-sim-" + secrets.token_hex(6)
            source.sendText(payload)
            deadline = time.monotonic() + 18
            while True:
                try:
                    row = received.get(timeout=max(0, deadline - time.monotonic()))
                except Empty:
                    raise TimeoutError("Peer did not receive the expected simulator text") from None
                if row == (target, source.myInfo.my_node_num, payload):
                    break
        print("PASS: two simulated firmware nodes delivered distinct text in both directions")


if __name__ == "__main__":
    check()
