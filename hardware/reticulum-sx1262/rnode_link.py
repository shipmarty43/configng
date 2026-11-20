"""Attach or detach only the optional Waveshare entry of the shared RNS instance."""
import argparse
from pathlib import Path
import sys
import time

import RNS
from RNS.vendor.configobj import ConfigObj
from sx1262_rx import FREQUENCY, BANDWIDTH, SF, CR

NAME = "Waveshare SX1262 RX"
CONFIG = Path("/var/lib/opi-reticulum")


def validate(path):
    interfaces = ConfigObj(str(path), file_error=True).get("interfaces", {})
    cfg = interfaces.get(NAME)
    expected = dict(type="RNodeInterface", enabled="no", outgoing="no", port="tcp://127.0.0.1",
                    frequency=str(FREQUENCY), bandwidth=str(BANDWIDTH), spreadingfactor=str(SF),
                    codingrate=str(CR), txpower="0", flow_control="yes")
    if cfg != expected:
        raise ValueError(f"Missing or incompatible disabled RX interface in {path}")


def present(rns):
    return next((i for i in rns.get_interface_stats()["interfaces"] if i.get("short_name")==NAME), None)


def manage(action, directory=CONFIG):
    if action == "attach":
        validate(directory/"config")
    rns = RNS.Reticulum(configdir=str(directory), require_shared_instance=True)
    if action == "detach":
        if present(rns) and not rns.detach_interface(NAME):
            raise RuntimeError("Could not detach Waveshare RX")
        return
    if present(rns):
        raise RuntimeError("Waveshare RX interface is already attached")
    try:
        if not rns.attach_interface(NAME):
            raise RuntimeError("RNS refused interface attachment")
        end = time.monotonic()+6
        while time.monotonic()<end:
            entry = present(rns)
            if entry and entry["type"]=="RNodeInterface" and entry["status"]:
                print("Waveshare RX: official RNodeInterface online")
                return
            time.sleep(.2)
        raise RuntimeError("RNode handshake did not finish")
    except BaseException:
        if present(rns):
            rns.detach_interface(NAME)
        raise


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=("attach","detach"))
    try:
        manage(cli.parse_args().action)
    except (ValueError,RuntimeError,OSError) as e:
        sys.exit(str(e))
