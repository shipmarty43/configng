# H618 Android/BSP CVBS reference

Research date: 2026-10-26. The owner clarified that Android TV-out support was
found in online reports, not personally tested. The Zero 2W manufacturer's
[manual v1.1](https://www.nikom.biz/pic_info/A704017/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf)
also lists TV-OUT as working for Android 12 TV / Linux 5.4 (section 6.2).
That is a vendor support statement, not a captured-picture test on this board.

## Source identity and limits

Inspected the official [Orange Pi BSP kernel](https://github.com/orangepi-xunlong/linux-orangepi/tree/3a4a29414d558664847202f4d8919b8ab8bcf4a8),
branch `orange-pi-5.4-sun50iw9`, commit
`3a4a29414d558664847202f4d8919b8ab8bcf4a8` (2026-04-17).
The branch contains the H618 Android configuration and the TV driver it selects.
It has not been matched byte-for-byte to a specific working Android image or
to the separate `opizero2w_android12_patches` archive described by the vendor.
Selected Android HAL and U-Boot sources from a community Android 12 port were
subsequently inspected; their provenance and limits are recorded below.

The adjacent [source manifest](zero2w-android-tve-sources.json) records exact
source links and SHA-256 hashes. The inspected driver files carry Allwinner's
GPL-2.0 notices; preserve those terms when deriving kernel code. No vendor
driver is installed or executed by this investigation.

## The implementation exists

| Layer | Source evidence | Meaning for the port |
|---|---|---|
| Build | `sun50iw9p1smp_h618_android_defconfig`: `CONFIG_ARCH_SUN50IW9`, `CONFIG_DISP2_SUNXI`, `CONFIG_TV_DISP2_SUNXI` enabled | Android uses the vendor disp2 implementation; finding only mainline sun4i DRM misses it |
| Low-level driver selection | `disp2/tv/Makefile` selects `de_tve_sun8iw11.o` for `CONFIG_ARCH_SUN50IW9` | The filename is not a reason to reject this file as unrelated to H618 |
| Resource description | `sun50iw9.dtsi` TV node: `allwinner,sunxi-tv`, TVE_TOP `0x06520000` / `0x100`, TVE `0x06524000` / `0x3fc` | Separate TOP/DAC and encoder register windows need explicit handling |
| Clocks and resets | Three clocks (`clk_bus_tve_top`, `clk_tve`, `clk_bus_tve`), two resets, assigned PLL_VIDEO1 parent | Bring up the complete clock/reset path, not just a TV status property |
| Calibration | DT `tvout` NVMEM cell; `drv_tv.c::__get_tv_cali_value()` and `tv_init()` | Read per-chip DAC calibration, with documented validation/fallback |
| Signal programming | `de_tve_sun8iw11.c::tve_low_set_tv_mode()` | Explicit PAL/NTSC register sequences, including chroma, sync and deflicker settings |
| DAC | `tve_low_init()`, `tve_low_dac_enable()`, `tve_low_open()` | DAC routing, analogue configuration and output enable are distinct steps |
| Display routing | `disp_tv.c`, `disp_al_tcon.c`, `tcon/de_lcd.c` | The DE manager and TCON route/timing must agree with the TV encoder |
| Userspace entry | `dev_disp.c::disp_ioctl()`, `DISP_DEVICE_SWITCH` / `DISP_DEVICE_SET_CONFIG` | The community Android source has a matching caller through `/dev/disp`; official-image linkage remains unverified |

All paths under `disp2` above are relative to
`drivers/video/fbdev/sunxi/disp2/`; full links are in the manifest.

## What the source actually does

During `tv_init()`, the driver reads DAC mapping/type and optional offset,
obtains calibration through NVMEM, enables clocks/resets, and detects whether
the bootloader already initialized TV-out through `boot_disp`. A boot-initialized
output takes a different path from a cold initialization. This matters when
testing Linux: a picture inherited from U-Boot does not prove the kernel can
initialize the encoder independently.

For a fresh enable, `tv_enable()` configures the TVE clock, programs the selected
mode, enables the DAC, adjusts resynchronization and opens the encoder.
`disp_tv_enable()` also enables the display manager and configures/enables TCON.
The SUN50IW9 TCON code uses the TVE-derived TV clock path and a specific YUV-range
setting. Port these dependencies to DRM atomic/resource handling, not disp2's
global state and ioctl machinery.

The timing table contains NTSC `720x480`, total `858x525`, and PAL `720x576`,
total `864x625`, each with a `216000000` clock value. **This is not a ready-made
216 MHz DRM connector pixel clock.** The BSP has special deflicker/clock-domain
semantics: its PAL/NTSC entries have `b_interlace=0`, while separate 480I/576I
entries exist. The low-level PAL/NTSC setup enables deflicker. Translate the
TCON/encoder clock relationship and field generation before defining DRM modes.

The low-level driver has a SUN50IW9-specific plug-detection path. The higher
layer exposes CVBS state through extcon when enabled. In mainline, detection
and mode reporting must integrate with the DRM connector lifecycle.

## Details that prevent a blind copy

- The NVMEM node is named `tvout@2e`, but its actual `reg` is `<0x2c 8>`.
  The helper reads a 32-bit word and shifts it by 16. Derive the calibration
  field from this access pattern and the SID specification, not the node name.
- Static review found an error path in `__get_tv_cali_value()`: failure of
  `nvmem_cell_get()` returns `PTR_ERR(caldata)` even though `caldata` has not
  been initialized there. A port must fix this and validate allocation lengths,
  endianness, calibration values and DAC indices.
- DAC properties (`interface`, `dac_src0`, `dac_type0`) are supplied by board
  configuration. The generic SoC node alone does not establish correct wiring.
- The checked-in **Zero 3** board DTS has TV disabled, even though it specifies
  these DAC properties. It is not the Zero 2W Android working DT; do not present
  it as such or transplant it wholesale.
- `tv_ac200.c` is a separate, selectable encoder implementation. The H618
  configuration and Makefile inspected here select the native TVE path;
  finding a file called AC200 is not evidence that this board's CVBS uses it.

## Zero 2W Android board configuration located

The [manufacturer's download page](http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/service-and-support/Orange-Pi-Zero-2W.html)
links these public downloads, inspected on 2026-10-26:

- [Source folder](https://drive.google.com/drive/folders/1TRHmKWy_tZoZ_1LySJAfJvfXvZ6zbNIn):
  `opizero2w_android12_patches.tar.gz`, displayed as 54 KB, dated 2023-09-14;
  [individual file](https://drive.google.com/file/d/15pDLyQyI33qOu0wAuXo5K9yeuw6X3Egy/view).
- [Image folder](https://drive.google.com/drive/folders/19QpUgDYF35BVyB9RI38BLKqtnIHtkh5k):
  `Orangepi_zero2w_android12_tv_v1.0.tar.gz`, displayed as 551.5 MB, dated
  2023-09-18;
  [individual file](https://drive.google.com/file/d/198QVyib3a1O_Pbu2y1H7KnRI0L7F3KoE/view).

Both downloads returned Google's **quota exceeded** page. No archive bytes,
archive hashes, or DTB extracted from that official image are available from
this attempt. The HTML responses were not retained as misleading `.tar.gz`
files. The vendor manual names the small patch archive as a prerequisite for
building Zero 2W, so a generic H618 source tree alone is insufficient evidence.

An independently published [OmniROM build manifest](https://github.com/YAJATapps/android_apollo-p2_local_manifest/tree/omni-12.1)
points to [Longan](https://gitlab.com/Yajat/android_longan/-/tree/47b861f18054c373241666c1ad3cb6ba0f265441)
and [Allwinner Android hardware sources](https://github.com/YAJATapps/android_hardware_aw/tree/eb2b7e7c8708284128fc170635d5f9bca2495048).
Its [author's build instructions](https://blogs.yajatkumar.com/2024/10/source-compilation-omnirom-121-for.html)
identify `h618/p2` as Zero 2W and `h618/p3` as Zero 3. The inspected p2 kernel
DTS itself says `model = "Orange Pi Zero2w"`. These are community sources,
**not a verified copy of the blocked vendor patch archive**.

Longan commit: `47b861f18054c373241666c1ad3cb6ba0f265441`.
Hardware/HAL commit: `eb2b7e7c8708284128fc170635d5f9bca2495048`.
The manifest records all reviewed file hashes and immutable URLs.

| Setting | p2 Linux 5.4 board DTS | p2 U-Boot board DTS | Interpretation |
|---|---|---|---|
| `tv0.status` | `okay` | `okay` | Native encoder enabled in both stages |
| `interface` | 1 | 1 | CVBS |
| `dac_src0`, `dac_type0` | 0, 0 | 0, 0 | DAC0, composite type |
| `screen0_output_type`, mode | 3, 10 | 3, 10 | HDMI, 1080p60 in this BSP's screen-property numbering |
| `screen1_output_type`, mode | 2, 11 | 2, 11 | TV, PAL (`0x0b`) |
| `dev0_output_type`, screen, HPD | 4, 0, 1 | 4, 0, 1 | HDMI boot candidate with detection |
| `dev1_output_type`, screen, HPD | 2, 1, 1 | 2, 1, 1 | TV boot candidate with detection |
| `def_output_dev` | 0 | 0 | HDMI fallback when no candidate is detected |

Do not confuse `screen*_output_type=3` with `DISP_OUTPUT_TYPE_HDMI=4` used by
`dev*` and ioctls. `dev_disp.c` explicitly converts the former numbering.
The PAL mode value is 11, not the separate `DISP_TV_MOD_576I=1` entry.

The p2 paths are `device/config/chips/h618/configs/p2/linux-5.4/board.dts`
and `.../p2/uboot-board.dts`. `build/mkcmd.sh::board_dts_create_link()` selects
the kernel-version-specific board DTS. The p2 `sys_config.fex` inspected here
contains no display/TV section. Nevertheless `build/pack` merges FEX input into
the generated DT using its vendor DTC, so source inspection does not replace
extracting the packed DTB or reading the live DT.

Most significantly, Longan's Linux 5.4 `drv_tv.c` and `de_tve_sun8iw11.c` are
**byte-for-byte identical** to the two official Orange Pi BSP files already
inspected above (SHA-256 comparison). This links the board configuration to
the exact TVE implementation, without claiming that all kernels or images are
identical. Its SoC DT also describes the same TOP/TVE windows, clocks, resets,
PLL_VIDEO1 parent and `tvout` calibration cell.

## U-Boot and Android selection path

In Longan's `brandy/brandy-2.0/u-boot-2018/drivers/video/sunxi/bootGUI/`:

1. `dev_manage.c::get_device_configs()` reads the `dev*` entries. Saved display
   configuration can override mode defaults.
2. `do_hpd_detect()` first checks the first candidate, then the list of
   candidates with HPD enabled. `disp_devices_open()` falls back to
   `def_output_dev` if detection fails. Thus an enabled TV node alone does not
   mean CVBS was selected at boot.
3. `video_hal.c::hal_save_boot_disp()` encodes `(type << 8 | mode)` into the
   16-bit slot for the chosen screen, plus separate format and colour data.
   If TV/PAL is selected on screen 1, the formula yields `0x020b0000` for
   `boot_disp`. This is a **derived diagnostic expectation**, not a measured
   value or a parameter to force into an Armbian command line.

In the published `hardware/aw/display` tree:

- `configs/dispconfigs/config.json` names `homlet-default.json`, whose two
  outputs are HDMI on DE port 0 and CVBS on port 1. This is the source-tree
  default; installation or runtime overrides in a particular image remain
  unverified.
- `libdisplayd/platform/platform.cpp` discovers HDMI/CVBS through extcon state.
  `CvbsDevice::performDefaultConfig()` returns without configuring TV when
  CVBS is disconnected; otherwise it accepts PAL/NTSC, with PAL as fallback.
- `CvbsDevice` inherits the `HardwareCtrl` path through `DeviceControler`.
  `HardwareCtrl::setDeviceConfig()` sends `DISP_DEVICE_SET_CONFIG` to
  `/dev/disp`, with the DE index and a configuration pointer. This reaches the
  already traced vendor kernel ioctl and TV enable sequence.
- `DefaultOutputPolicy` supports single/dual output. When the primary is
  absent and the external output is connected, it can map the latter to the
  primary display. This explains a possible HDMI-unplugged CVBS workflow;
  it is not evidence that a particular Android image has this policy active.

These sources also contain defects that should not be copied: the same
uninitialized calibration error pointer noted above, and a partially initialized
`disp_device_config newconfig` in `CvbsDevice::performDefaultConfig()` (for
example, `cs` is not assigned before submission). A DRM port should use its
own validated configuration and resource lifecycle.

## Next evidence needed

1. Obtain the vendor Zero 2W Android image/board patch archive and extract its
   actual kernel DT, boot display parameters and relevant configuration. Record
   file hashes and versions. The official links and community reference are
   now known; quota prevented the official-image comparison. No need to build
   the entire Android distribution merely to inspect these files.
2. Boot that image on a test SD and capture PAL/NTSC with the owner's EasyCAP.
   Record USB ID/driver, selected standard, kernel log and DT. Avoid dumping
   unrelated Android account data or enabling network ADB for this purpose.
   Test with HDMI disconnected and connected, attaching the powered EasyCAP
   before cold boot. Record extcon state as well as the picture, since both
   bootloader and Android selection can depend on load detection. Through an
   already authorized local USB ADB connection, collect `uname -a`,
   `getprop ro.build.fingerprint`, `getprop ro.product.model`, `/proc/cmdline`
   and `/sys/firmware/fdt` when readable; an unavailable file is a collection
   failure to report, not a reason to change permissions or root the device.
3. Choose the target Armbian kernel and implement the encoder/DAC, binding,
   calibration and TCON-routing changes there. Start with a controlled test
   pattern and verify cold initialization and clean disable before desktop use.

The earlier [hardware acceptance plan](zero2w-cvbs.md) still applies. We now have
a concrete, licensed source reference; we do not yet have a working DRM port or
a verified Android capture on this physical board.
