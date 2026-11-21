"""Run in a private /dev and loopback-only netns, using an upstream framing oracle."""
import argparse
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time

import RNS
from RNS.Interfaces.RNodeInterface import RNodeInterface
from RNS.vendor.configobj import ConfigObj
import rnode_adapter
from rnode_adapter import ADDRESS, Session, serve
from rnode_wire import kiss
from sx1262_rx import FREQUENCY, Receiver
from sx1262_model import Model
from rnode_link import NAME


def encoded(oracle, payload):
    data=subprocess.check_output([oracle,"encode"],input=payload)
    frames=[]
    while data:
        n=data[0]; assert n and len(data)>=1+n
        frames.append(data[1:1+n]); data=data[1+n:]
    return frames


def wait_for(check, timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if check(): return
        time.sleep(.025)
    raise TimeoutError("peer did not reach expected state")


def run(oracle, hz):
    from sx1262_tx import Transceiver

    assert {n for _,n in socket.if_nameindex()}=={"lo"}
    assert not any(Path("/dev").glob("spidev*")) and not any(Path("/dev").glob("gpiochip*"))
    model=Model(hz, Transceiver)
    assert bytes.fromhex("8b09040100") in model.ops and bytes.fromhex("8c001200ff0100") in model.ops
    assert bytes.fromhex("0d07401424") in model.ops and model.registers[0x736]&4
    assert bytes.fromhex("9d01") in model.ops and len(model.settings)==4
    assert [op for op in model.ops if op[0]==0x86]==[b"\x86"+round(FREQUENCY*2**25/32000000).to_bytes(4,"big")]
    stopped=threading.Event()
    inbound=queue.Queue()
    class Owner:
        def inbound(self,data,interface): inbound.put(bytes(data))
    with socket.create_server(ADDRESS,backlog=1) as listener, tempfile.TemporaryDirectory() as directory:
        config=Path(directory)/"config"
        config.write_text("[reticulum]\n share_instance = yes\n instance_name = opi-rnode-acceptance\n"
                          "[interfaces]\n"+Path(rnode_adapter.__file__).with_name("rnode-interface.conf").read_text())
        rns=RNS.Reticulum(configdir=directory)
        thread=threading.Thread(target=serve,args=(model.radio,listener,stopped.is_set),daemon=True)
        thread.start()
        iface=None
        try:
            profile=ConfigObj(str(config))["interfaces"][NAME].dict()
            iface=RNodeInterface(Owner(),dict(profile,name=NAME))
            assert iface.online and iface.detected and iface.firmware_ok
            assert (iface.r_frequency,iface.r_bandwidth,iface.r_sf,iface.r_cr,iface.r_txpower,iface.r_state)==(FREQUENCY,125000,9,5,0,1)
            for size in (1,2,253,254,255,256,500,507,508):
                data=(b"\xc0\xdb"+bytes(range(256)))*2
                data=data[:size]
                frames=encoded(oracle,data)
                for frag in frames: model.frames.put((2,frag))
                assert inbound.get(timeout=6)==data
                iface.process_outgoing(data)
                virtual=[model.out.get(timeout=6) for _ in range((size + 253) // 254)]
                stream=b"".join(bytes([len(f)])+f for f in virtual)
                assert subprocess.check_output([oracle,"decode"],input=stream)==data
                wait_for(lambda:iface.interface_ready)
            iface.detach(); iface=None
            time.sleep(1)
            # Attach via actual shared-instance RPC and deliver an application packet.
            subprocess.run([sys.executable,"-c","import rnode_link,sys;from pathlib import Path;"
                            "rnode_link.manage('attach',Path(sys.argv[1]))",directory],check=True,timeout=20)
            attached=next(i for i in RNS.Transport.interfaces if i.name==NAME)
            assert attached.online and not attached.OUT
            event=queue.Queue()
            dest=RNS.Destination(None,RNS.Destination.IN,RNS.Destination.PLAIN,"opirnode","proof")
            dest.set_packet_callback(lambda data,packet: event.put((bytes(data), packet.rssi, packet.snr)))
            target=RNS.Destination(None,RNS.Destination.OUT,RNS.Destination.PLAIN,"opirnode","proof")
            packet=RNS.Packet(target,b"RNode -> Waveshare -> RNS")
            packet.pack()
            for frame in encoded(oracle,packet.raw): model.frames.put((2,frame))
            assert event.get(timeout=5) == (b"RNode -> Waveshare -> RNS", -103, -7.25)
            subprocess.run([sys.executable,"-c","import rnode_link,sys;from pathlib import Path;"
                            "rnode_link.manage('detach',Path(sys.argv[1]))",directory],check=True,timeout=15)
            assert not any(i.name==NAME for i in RNS.Transport.interfaces)
            # Production Receiver explicitly rejects data even from a misconfigured sender.
            s=Session(Receiver(model.spi, model)); s.configured=set(range(1,6)); s.handle(6,b"\1")
            assert s.handle(0,b"deny")==kiss(0x90,b"\2")
            s.close()
            print(f"PASS: RNS {RNS.__version__} official RNodeInterface detect/config/flow control; nine boundary sizes in both software directions")
            print(f"PASS: reference firmware frames -> SX1262 FIFO -> RNS application; live attach/detach; physical TX refused; SPI mode 0, {hz} Hz, 8-bit MSB-first")
        finally:
            if iface: iface.detach()
            stopped.set(); thread.join(3)
            assert not thread.is_alive()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle",type=Path); parser.add_argument("hz",type=int)
    args=parser.parse_args(); run(args.oracle,args.hz)
