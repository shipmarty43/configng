# Orange Pi Zero 2W native CVBS on Armbian

This directory contains the experimental H618 DRM component, changes to the
sun4i display driver, and a boot-time overlay for Orange Pi Zero 2W running
Armbian `6.18.57-current-sunxi64`. The composite profile uses DAC0 on the
24-pin expansion connector. PAL is the default. HDMI uses the same TCON-TV0
and is disabled in this profile. Removing the overlay restores the stock
graph on the next boot. The kernel patch must accompany the overlay.

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

The [TVE binding](allwinner,sun50i-h618-tv-encoder.yaml) describes these resources.

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
| ARM64 kernel objects | Both core objects compiled with Kbuild W=1 against the original Armbian headers (deb SHA-256 187ee5a741f2277b67eb3a69be8e5fb149b30df1335b2b6b7a2c8c1441336838). |
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

## DRM route and timings

The board graph connects the DE33 mixer through TCON_TOP to TCON-TV0. The new
branch uses output port 1, endpoint 0 on TCON-TV0, input port 0 on TVE, and
output port 1 on TVE to the physical composite connector. The sun4i component
master stops at the passive connector. The TVE component creates a TVDAC
encoder, derives its CRTC mask from the input graph, and registers a DRM
Composite connector with the standard TV mode property. There is no cable
sensing in this version.

| DRM mode at the jack | Input supplied to the encoder |
|---|---|
| PAL 720×576i, 50 fields/s | 720×576 progressive, 864×625 total, 27 MHz |
| NTSC 720×480i, approximately 59.94 fields/s | 720×480 progressive, 858×525 total, 27 MHz |

The BSP enables the TVE deflicker for both standards. Its divide-by-eight
pixel clock comes from the 216 MHz TVE module. The TCON_TOP driver selects
this parent in TV_SETUP bit 0 and registers the divider and gate with the
common clock framework. The original CCU path is selected for HDMI boots.
The connector checks the requested TV standard against the wire timing and
rejects cloning. TCON and mixer receive the full-frame adjusted mode.
[Vendor timing table](https://github.com/orangepi-xunlong/linux-orangepi/blob/3a4a29414d558664847202f4d8919b8ab8bcf4a8/drivers/video/fbdev/sunxi/disp2/tv/drv_tv.c)
· [Vendor TCON route](https://github.com/orangepi-xunlong/linux-orangepi/blob/3a4a29414d558664847202f4d8919b8ab8bcf4a8/drivers/video/fbdev/sunxi/disp2/disp/de/lowlevel_v33x/tcon/de_lcd.c)

## Reproduce the offline checks

The stock DTB was extracted from
`/boot/dtb-6.18.57-current-sunxi64/allwinner/sun50i-h618-orangepi-zero2w.dtb`
in the owner's `26.11.0-trunk.108` XFCE image. The image build revision is
`fac57a02f`. The separate kernel package was built on October 21 and records
Linux `2ff600d29ee478d0a8d46ef8a58afb5e038fe692` and patch hash
`6641bab59d342c0a`. For the DRM build we reconstructed the sun4i directory
from Linux 6.18.57 and applied the 43 enabled Armbian patches touching it
in the package-date series, in order. Its Makefile matches the one in the
archived board headers. [Armbian patch series](https://github.com/armbian/build/blob/e4de830005f0d616fed576a9c046f3a8aeb24ef8/patch/kernel/archive/sunxi-6.18/series.conf)

From the configng checkout, set `KERNEL` to the already Armbian-patched kernel
source, `HEADERS` to the prepared arm64 headers and `STOCK_DTB` to the original
binary DTB. The following produces one kernel patch, applies it to the chosen
source checkout and compiles the display subsystem. The DT test needs
`cpp`, `dtc`, `fdtoverlay`, `fdtget` and `fdtput`.

```sh
cvbs=$PWD/hardware/cvbs
out=$(mktemp -d)
"$cvbs/kernel-patch.sh" > "$out/h618-cvbs.patch"
git -C "$KERNEL" apply --check "$out/h618-cvbs.patch"
git -C "$KERNEL" apply "$out/h618-cvbs.patch"
make -C "$HEADERS" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- W=1 \
    M="$KERNEL/drivers/gpu/drm/sun4i" MO="$out/sun4i" built-in.a
"$cvbs/tests/check-arm64.sh" "$HEADERS" "$KERNEL"
"$cvbs/tests/check-de33.sh" "$HEADERS" "$KERNEL"
"$cvbs/tests/check-bars.sh"
python3 "$cvbs/tests/check-dtb.py" "$STOCK_DTB" "$HEADERS" --output "$out/profile"
```

| Offline check on 2026-11-19 | Result |
|---|---|
| SHA-256 of stock DTB | `4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758` |
| DTBO and merged DTB with dtc 1.7.2 | SHA-256 `b5a01066debb8e6032faa5ba6cf0873318fbe6d62ccf09736453ee8b7290790b` and `f629e8d2a1b612d0534fee75aff395fecc113922da9cc7b23fa145453c5d01aa` |
| Graph and resources | Reciprocal endpoints, disabled HDMI branch, CCU gates and resets, independent SID TV and Ethernet cells. Corrupted reverse link, second active output and short trim cell rejected by the checker. |
| DT schemas | New TVE and revised TCON_TOP bindings passed dt-doc-validate. Scoped dt-validate on the merged DTB passed for TVE, TCON_TOP, the analog jack and fixed layout. |
| Kernel build | Combined patch applied cleanly. The target sun4i DRM directory built with ARM64 Kbuild W=1 and the archived configuration. |
| QEMU AArch64 | Executed the component's mode validation and atomic check with the Linux DRM mode helpers. Both wire-to-input conversions passed. Mismatched TV standard, clone and altered timings were rejected. |

## DE33 colour and boot test, 2026-11-20

The target DE33 driver advertises RGB framebuffers on both UI and VI planes.
When the CRTC selects the TVDAC encoder, each visible RGB plane programs its
channel CSC with the vendor DE330 full-range RGB to limited-range BT.601
matrix. The blender selects YCbCr and uses Y=16, Cb=Cr=128 for background and
pipe fill. When the CRTC selects HDMI the plane conversion is bypassed and the
black level returns to RGB zero. This uses the physical plane register window
at channel offset `0x800 + channel * 0x20000`. The SUN50IW9 BSP also disables
the TCON colour unit’s range limiter for TV output.
[Vendor conversion table](https://github.com/orangepi-xunlong/linux-orangepi/blob/3a4a29414d558664847202f4d8919b8ab8bcf4a8/drivers/video/fbdev/sunxi/disp2/disp/de/lowlevel_v33x/de330/de_csc_table.c) ·
[Vendor TV path](https://github.com/orangepi-xunlong/linux-orangepi/blob/3a4a29414d558664847202f4d8919b8ab8bcf4a8/drivers/video/fbdev/sunxi/disp2/disp/de/lowlevel_v33x/disp_al_tcon.c)

| Check | Result |
|---|---|
| Kbuild ARM64 CSC and mixer code, bounded register windows | Eight RGB bars decoded to their expected BT.601 values on channels 0, 6, 7, 1, 2 and 8. CVBS → HDMI → CVBS restored the plane and blender settings. |
| Stock-board DTB | Overlay reapplied. The merged DTB matched the previously verified SHA-256. |
| Diagnostic kernel | The complete ARM64 Image linked and booted to an external initramfs in QEMU with 256 MiB RAM. |
| Virtual DRM scanout | The guest held a 640×480 XR24 framebuffer on VKMS. DRM debugfs showed an active CRTC with a framebuffer, then an inactive CRTC after release. |
| PAL/NTSC diagnostic commands | Fixture checked the exact mode index, plane, TV enum (including NTSC=0) and rejection of a missing standard. The encoder timings and register sequences also passed the ARM64 tests above. |

The [RAM boot and serial-console guide](probe/README.md) covers rebuilding the
kernel, repeating the QEMU check and booting it once from U-Boot. The first
physical milestone is a cold probe of the Composite connector and an EasyCAP
capture in each standard. Record sync, colour, shutdown and HDMI recovery on
the normal boot profile.
[EasyCAP procedure](../../tests/hardware/zero2w-cvbs.md) ·
[Official Android image evidence](../../tests/hardware/zero2w-official-android.md)
