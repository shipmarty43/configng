# Orange Pi Zero 2W: native CVBS bring-up

Status, 2026-10-26: **research / hardware validation pending**. This is not an
enablement overlay or a claim that TV-out works on the current Armbian image.
The owner has the 24-pin expansion board and an EasyCAP USB capture device.
The target is the board's native CVBS output, not HDMI-to-AV conversion.

Follow-up: the official Orange Pi BSP contains an H618 Android configuration
and a concrete native TVE implementation. See the
[Android/BSP source investigation](zero2w-android-tve.md) and its pinned source
manifest. Android support is documented by the vendor and reported online;
the owner has not yet personally verified it with the EasyCAP.
The [official Android image has now been inspected offline](zero2w-official-android.md):
its Linux 5.4.125 configuration enables native TVE and its kernel DT selects
DAC0/CVBS with PAL as the TV default. This supplies a baseline to test, not an
Armbian enablement overlay.

## Evidence

The manufacturer's [Zero 2W manual v1.1, mirrored copy](https://orangepi.net/wp-content/uploads/2023/10/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf)
lists TV-out among the 24-pin expansion functions. Verify the exact board
revision, connector orientation and AV connector wiring against its schematic
before making a cable. No pin number or TRRS contact order is assumed here.

[Allwinner H616 manual v1.0](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf),
section 7.2, printed pages 435 onward, describes one CVBS channel, PAL-D and
NTSC-M, a 10-bit DAC, plug detection and efuse-based DAC calibration. The
specified TVE clock for both standards is 216 MHz. The register list (page 438)
gives TVE_TOP at `0x06520000` and TVE at `0x06524000`. CCU clock/reset registers
are described around pages 119–120. These are H616 reference facts to check
against H618; register similarity is not proof of complete compatibility.

In upstream **Linux v6.18**, the [H616 CCU driver](https://github.com/torvalds/linux/blob/v6.18/drivers/clk/sunxi-ng/ccu-sun50i-h616.c)
contains TVE clocks and resets. However, the examined
[sun4i TV encoder driver](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/sun4i/sun4i_tv.c)
matches only `allwinner,sun4i-a10-tv-encoder`. This does not establish support
for the H616/H618 TVE_TOP/DAC design. Do not add an A10 compatible string merely
to force a probe. This check is pinned to v6.18, not a claim about every vendor
tree or every later Linux version.

The DTB inspected on the owner's old Armbian 6.12.47 SD contains an HDMI path
with `tcon-tv` but no TV encoder node at these TVE addresses. TCON-TV is a timing
controller also used by HDMI; its name is not evidence of a composite encoder.
The `gpu` and `i2c1-pi` overlays were the owner's experiments with enabling or
replacing modules and are not a known-working CVBS configuration.

## Keep responsibilities separate

- Kernel/board support: DE mixer → TCON routing → TVE → DAC, clocks/resets,
  regulators, calibration, connector modes and DT bindings.
- Configurator: show actual capabilities; select a supported PAL/NTSC mode only
  once the kernel exposes a validated connector; report failures and support
  reverting the boot configuration.
- Desktop/DM: choose a session and its display settings. Neither implements
  the missing encoder, and GPU 3D acceleration is a separate capability.

Do not invent a loadable overlay before the target kernel and driver bindings
are selected. Preserve the old SD; use a test image for kernel/DT changes.
Kernel work belongs in a kernel patch series, not register writes from this
root configurator. No MMIO writes or SD changes are part of this feature.

## Bring-up sequence

1. Record the chosen Armbian image, kernel source commit, patch set and live DT.
   Compare that kernel's CCU, TCON routing and TVE implementation with the H616
   manual and any licensed vendor reference driver. Confirm H618 differences.
2. Verify the expansion-board CVBS path and DAC supply from the schematic.
   Retain serial-console/SSH recovery during display development.
3. Implement/review the missing DRM encoder/DAC and DT binding changes. Test
   resource cleanup, clock/reset sequencing, calibration and atomic enable/
   disable. Build the kernel and validate DT schemas before booting the test SD.
4. Confirm the running kernel exposes the intended composite connector and
   inspect its advertised modes/properties with `modetest -c` or `drm_info`.
   Do not substitute an invented connector name or copy HDMI timings.
5. Identify EasyCAP on the capture computer with `lsusb`,
   `v4l2-ctl --list-devices`, then query the chosen capture node with
   `v4l2-ctl -d /dev/videoN --list-inputs`, `--list-standards` and
   `--list-formats-ext`. EasyCAP is a product family; record the USB ID, driver
   and supported formats rather than assuming one chipset or `/dev/video0`.
6. Test the capture chain with a known-good composite source if available.
   Select matching PAL or NTSC on transmitter and capture input. Display colour
   bars, a geometry grid and moving content from the Pi. Check sync lock, colour,
   interlacing, overscan, dropouts and reported capture errors.
7. Exercise cold boot, repeated enable/disable, cable removal and recovery,
   both supported standards and HDMI coexistence if advertised. Record failures
   and power/temperature behaviour. Then expose the proven modes in configng.

EasyCAP alone cannot establish electrical levels or DAC calibration accuracy;
use appropriate measurements when investigating those issues. A captured
picture and successful boot are necessary evidence, not a substitute for the
remaining repeatability tests.

## Acceptance record

| Item | Evidence required | Current state |
|---|---|---|
| Board + expansion revision | Schematic and verified CVBS wiring | Pending |
| Kernel + DTB | Exact commits, patches, build and schema checks | Target image unselected |
| DRM encoder | Probe, connector, advertised modes, clean disable | Pending |
| PAL / NTSC | Capture clips, settings and EasyCAP USB ID | Pending |
| Recovery / repeatability | Boot, mode switching, cable tests | Pending |
| Configurator controls | Only validated modes, reversible settings | Gated on driver validation |
