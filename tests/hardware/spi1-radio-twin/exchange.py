"""Run the shipped identification paths over one emulated Linux SPI controller."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import threading

sys.path.insert(0,"/triple")
from core.header_peripherals import identify
from core.radio_lock import acquire_radio

CONFIG = json.loads(Path("/triple/profile.json").read_text())
KINDS = ("lora","subghz","nrf24")
PARAMS = Path("/sys/module/qa_spi1/parameters")
ROUNDS = 32


def read(cs):
    response = identify(KINDS[cs], CONFIG)
    assert response["spi"] == f"spidev7.{cs}" and response["cs_header"] == (40,26,24)[cs], response
    assert response["clock_hz"] == (2_000_000,1_000_000,4_000_000)[cs], response
    if cs == 0: assert response["status"] == "0x24", response
    if cs == 1: assert (response["part"],response["version"],response["marcstate"]) == (0,20,"0x1"), response
    if cs == 2: assert (response["status"],response["channel"],response["rpd_latch"]) == ("0xe",76,0), response


def lock_matrix(cs):
    if cs == 0:
        command = ["/sx/lorawan-hal-tests","lock","/run/lock/opi-radio.lock"]
    else:
        command = [sys.executable, "-I", "-c",
                   "import sys;sys.path.insert(0,'/triple');from core.radio_lock import acquire_radio;"
                   "lease=acquire_radio(int(sys.argv[1]));print('locked',flush=True);sys.stdin.read(1)",str(cs)]
    child = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline() == b"locked\n"
        try: read(cs)
        except BlockingIOError: pass
        else: raise AssertionError(f"second owner acquired CS{cs}")
        for peer in range(3):
            if peer != cs: read(peer)
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
    read(cs)


def counters(name):
    return tuple(map(int,(PARAMS/name).read_text().strip().split(",")))


for cs in range(3): lock_matrix(cs)
print("PASS device locks: held CS excluded only its own client; both peers responded; SIGKILL released ownership", flush=True)

barrier = threading.Barrier(3,timeout=30)
def worker(cs):
    for _ in range(ROUNDS):
        barrier.wait()
        read(cs)
with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(worker,range(3)))

expected = tuple((ROUNDS+3)*reads for reads in (1,3,3))
assert counters("count") == expected
assert counters("asserts") == expected
assert all(counters(n) == (0,) for n in ("active","overlaps","rejected"))
print("PASS SPI1 three clients: accepted transfers",expected,"verified active-low selects (40,26,24); overlap=0, rejected=0, all CS idle",flush=True)
