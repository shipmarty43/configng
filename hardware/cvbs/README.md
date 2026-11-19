# Orange Pi Zero 2W native CVBS encoder core

This patch-development directory contains a Linux regmap implementation for the
H618 encoder and DAC0. It targets the kernel used on the project's Zero 2W,
Armbian `6.18.57-current-sunxi64`. A DRM connector and TCON routing are the
next integration steps. Nothing here registers a platform driver or changes a
boot configuration. The Zero 3W/A733 has a different display subsystem.

## Driver contract

- `h618_cvbs_acquire()` acquires managed MMIO/clock/reset handles and reads the
  raw `tvout` NVMEM cell. Device availability and NVMEM errors, including probe
  deferral, propagate to the caller. The Android cell begins at SID offset 0x2c.
  The halfword at bytes 2 and 3 of its first little-endian word holds the trim.
  A zero field selects the vendor H618 default (625). Values beyond the DAC's
  10-bit range and short cells fail. The board Android DT specifies no trim offset.
- `h618_cvbs_enable()` requires the caller to own the display route and analog
  supply, and to serialize transitions. It establishes reset state, requests the
  dedicated TVE module clock at 216 MHz, verifies its rate and programs the mode
  before opening the encoder. It preserves the BSP write order and uses separate
  encoder and TOP regmaps. Mode changes require disable followed by enable.
- `h618_cvbs_disable()` closes the encoder, mutes DAC0, asserts resets and
  releases clocks and the rate reservation. A real I/O/reset failure still
  requires recovery by the caller. Android's optional idle cable detection
  would keep part of the analog block powered. This prototype uses a full mute.

Proposed resource names for the future DT binding follow the driver's lookups:

| Type | Name | Target reference |
|---|---|---|
| MMIO | top, encoder | 0x06520000 / 0x100 and 0x06524000 / 0x3fc |
| CCU clocks | top-bus, tve, bus | CLK_BUS_TVE_TOP, CLK_TVE0, CLK_BUS_TVE0 |
| CCU resets | top, encoder | RST_BUS_TVE_TOP, RST_BUS_TVE0 |
| NVMEM | tvout | Aligned raw cell starting at SID+0x2c with at least four bytes, as in the packed Android DT |

The target's existing Ethernet cell at SID+0x2c is **two bytes**. Passing it as
the TV calibration cell would read the wrong field. Preserve it when defining
the TV cell. The baseline Linux SID provider specifies a four-byte stride.
[Linux SID provider](https://github.com/gregkh/linux/blob/2ff600d29ee478d0a8d46ef8a58afb5e038fe692/drivers/nvmem/sunxi_sid.c)

## Offline verification, 2026-11-19

The register comparison compiles functions from the SHA-256-checked
[Orange Pi GPLv2 BSP](https://github.com/orangepi-xunlong/linux-orangepi/tree/3a4a29414d558664847202f4d8919b8ab8bcf4a8/drivers/video/fbdev/sunxi/disp2/tv)
as a reference. Both implementations access separate, bounds-checked RAM windows.
Every read/write to TOP or TVE is compared in order, including repeated writes
and the default resync operation. Shutdown is compared against the BSP's
low-level close and DAC-disable functions. This reference is distinct from a
trace of the running Android binary.

| Run | Observed result |
|---|---|
| Native and static AArch64/QEMU differential tests | PAL: 48 start + 6 stop register accesses. NTSC: 46 + 6. Both matched, including trim values 1 and 1023 in boundary cases. |
| Fault injection on every start access | The port returned the error and muted output after a single transient read/write failure at each tested position. |
| ARM64 kernel objects | Both compiled with Kbuild W=1 against the original Armbian headers (deb SHA-256 187ee5a741f2277b67eb3a69be8e5fb149b30df1335b2b6b7a2c8c1441336838). |
| Actual ARM64 Kbuild power sequencing under QEMU with clock/reset test doubles | 12 enable and 3 disable failure positions, rejected rounded clock rate, duplicate enable and inactive disable. All tested resource references were released. |

Run from the configng repository root with a local checkout of the BSP at the
revision above. The optional QEMU runs need a static AArch64 libc toolchain and
`qemu-aarch64`.

```sh
python3 hardware/cvbs/tests/compare_bsp.py /path/to/linux-orangepi
python3 hardware/cvbs/tests/compare_bsp.py --arm64 /path/to/linux-orangepi
hardware/cvbs/tests/check-arm64.sh /path/to/prepared/6.18.57-current-sunxi64
```

For the archived headers, extract the .deb into a build directory. If host
fixdep is missing there, build it inside that extracted copy using
`cc -O2 -I"$KDIR/scripts/include" "$KDIR/scripts/basic/fixdep.c" -o "$KDIR/scripts/basic/fixdep"`.
The target kernel was built with GCC 14.2; this cross-build used GCC 15.2.
These tests cover compiled code and resource bookkeeping. Physical clocks,
NVMEM values, colour, sync and HDMI coexistence require the board.

## Integration against the board DTB

Inspected the original DTB directly from the local Zero 2W Armbian
26.11.0-trunk.108 XFCE image without mounting or changing it. Its SHA-256 is
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
TCON-TV0 at 0x06515000 has one output endpoint, linked to TCON_TOP's HDMI
input (reciprocal phandles 0x42/0x49). TCON_TOP's HDMI output goes to HDMI
(0x3a/0x43). The DT has no encoder at the two Android TVE register windows.
The phandles describe this artifact and must not be embedded in an overlay.

Next, integrate the register core with the target sun4i DRM component, define
the binding and alternate graph route, select the TCON TV clock source, and
arrange the YUV colour path and interlaced timings. Account for shared clocks
and route ownership with HDMI in the atomic check. The 216 MHz TVE module
clock is distinct from the DRM pixel clock. First-board acceptance includes
cold PAL/NTSC capture and HDMI recovery on a separate test image.
[Hardware procedure](../../tests/hardware/zero2w-cvbs.md)
· [Official Android image evidence](../../tests/hardware/zero2w-official-android.md)
