# H618 Android/BSP CVBS reference

Research date: 2026-10-26. The owner clarified that Android TV-out support was
found in online reports, not personally tested. The Zero 2W manufacturer's
[manual v1.1](https://orangepi.net/wp-content/uploads/2023/10/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf)
also lists TV-OUT as working for Android 12 TV / Linux 5.4 (section 6.2).
That is a vendor support statement, not a captured-picture test on this board.

## Source identity and limits

Inspected the official [Orange Pi BSP kernel](https://github.com/orangepi-xunlong/linux-orangepi/tree/3a4a29414d558664847202f4d8919b8ab8bcf4a8),
branch `orange-pi-5.4-sun50iw9`, commit
`3a4a29414d558664847202f4d8919b8ab8bcf4a8` (2026-04-17).
The branch contains the H618 Android configuration and the TV driver it selects.
It has not been matched byte-for-byte to a specific working Android image or
to the separate `opizero2w_android12_patches` archive described by the vendor.
The complete Android userspace/HAL and bootloader sources were not downloaded.

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
| Userspace entry | `dev_disp.c::disp_ioctl()`, `DISP_DEVICE_SWITCH` / `DISP_DEVICE_SET_CONFIG` | Known vendor kernel API; the Android HAL caller still needs tracing in the matching source/image |

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

## Next evidence needed

1. Obtain the vendor Zero 2W Android image/board patch archive and extract its
   actual kernel DT, boot display parameters and relevant configuration. Record
   file hashes and versions. No need to build the entire Android distribution
   merely to inspect these files.
2. Boot that image on a test SD and capture PAL/NTSC with the owner's EasyCAP.
   Record USB ID/driver, selected standard, kernel log and DT. Avoid dumping
   unrelated Android account data or enabling network ADB for this purpose.
3. Choose the target Armbian kernel and implement the encoder/DAC, binding,
   calibration and TCON-routing changes there. Start with a controlled test
   pattern and verify cold initialization and clean disable before desktop use.

The earlier [hardware acceptance plan](zero2w-cvbs.md) still applies. We now have
a concrete, licensed source reference; we do not yet have a working DRM port or
a verified Android capture on this physical board.
