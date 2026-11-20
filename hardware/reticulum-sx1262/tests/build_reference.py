"""Compile upstream RNode's pinned TX/RX framing with a memory-only FIFO."""
import argparse
import hashlib
import re
from pathlib import Path
import subprocess
import tempfile

REV = "56775c51b60a6190242e324c210997dcc7637e53"
DIGEST = "e29f4c22086ac8d9204555433c460add27638866b9c4e41817e06a40911fae3e"

# The MCU-independent paths of the pinned functions use this in-memory board.
MOCK = r"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <stdexcept>
#define MCU_VARIANT 1
#define MCU_NRF52 2
#define MCU_ESP32 3
#define ISR_VECT
// UPSTREAM_CONSTANTS
constexpr int ERROR_MODEM_TIMEOUT=1, ERROR_TXFAILED=2;
bool radio_online=true, promisc=false, implicit=false;
uint8_t tbuf[MTU], pbuf[MTU]; int seq=SEQ_UNSET;
int read_len=0, host_write_len=0, last_rssi=0, last_snr_raw=0;
// UPSTREAM_HEADER_HELPERS
long random(int){return 0xa7;}
void kiss_indicate_error(int){throw std::runtime_error("reference error");}
void led_indicate_error(int){} void hard_reset(){std::abort();}
void led_tx_on(){} void led_tx_off(){} void add_airtime(int){}
void kiss_indicate_stat_rssi(){} void kiss_indicate_stat_snr(){}
void kiss_write_packet(){std::fwrite(pbuf,1,read_len,stdout);}
struct FIFO {
    std::vector<uint8_t> buf; size_t offset=0;
    void beginPacket(int = 0){buf.clear(); offset=0;}
    void write(uint8_t b){buf.push_back(b);}
    bool endPacket(){if(buf.size()>255) std::abort();std::putchar(buf.size());std::fwrite(buf.data(),1,buf.size(),stdout);return true;}
    int read(){return buf.at(offset++);} int packetRssi(){return -80;} int packetSnrRaw(){return 12;}
} fifo, *LoRa=&fifo;
"""
MAIN = r"""
int main(int argc,char**argv){
    if(argc!=2)return 2;
    if(argv[1][0]=='e'){size_t n=std::fread(tbuf,1,MTU,stdin);if(!n || std::getchar()!=EOF)return 2;transmit(n);}
    else {int n;while((n=std::getchar())!=EOF){if(n==0)return 2;fifo.beginPacket();fifo.buf.resize(n);
      if(std::fread(fifo.buf.data(),1,n,stdin)!=(size_t)n)return 2;receive_callback(n);}}
}
"""


def build(source, output):
    raw = (source/"RNode_Firmware.ino").read_bytes()
    if hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError(f"Expected RNode_Firmware {REV}")
    headers = {}
    for name,digest in (("Config.h","600d00a1fd7f7828bfe857a826c0a5b4d10eb9727b713dc45ad4e6bdea012227"),
                        ("Utilities.h","d3957f85ee5d8ea5980c5fd64ccdb6a7a6ddbd73bc7d7b61ba9fd5d7d34113e4"),
                        ("Framing.h","2cd09e17dfc3b8029fd97347a004639743db4f887f33399e0a2a1d5e1da381a9")):
        data=(source/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError("Unexpected upstream "+name)
        headers[name]=data.decode()
    constants = []
    for name in ("MTU","SINGLE_MTU","HEADER_L","FLAG_SPLIT","SEQ_UNSET"):
        text = headers["Config.h"] if name in ("MTU","SINGLE_MTU","HEADER_L") else headers["Framing.h"]
        constants.append(re.search(r"^[ \t]*#define[ \t]+"+name+r"[ \t]+[^\n]+",text,re.M)[0])
    util=headers["Utilities.h"]
    helpers=util[util.index("inline bool isSplitPacket("):util.index("void setPreamble()")]
    mock=MOCK.replace("// UPSTREAM_CONSTANTS", "\n".join(constants)).replace("// UPSTREAM_HEADER_HELPERS",helpers)
    ino = raw.decode()
    rx = ino[ino.index("inline void getPacketData("):ino.index("bool startRadio()")]
    tx = ino[ino.index("void transmit(uint16_t size) {"):ino.index("void serial_callback(uint8_t sbyte) {")]
    with tempfile.TemporaryDirectory() as tmp:
        cpp = Path(tmp)/"reference.cpp"
        cpp.write_text(mock + rx + tx + MAIN)
        subprocess.run(["c++","-std=c++17","-O1",str(cpp),"-o",str(output)],check=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    build(args.source,args.output)
