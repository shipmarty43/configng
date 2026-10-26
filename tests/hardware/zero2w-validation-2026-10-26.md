# Orange Pi Zero 2W: configuration and graphics validation

Physical board, 2026-10-26. Armbian community 26.11.0-trunk.108,
Ubuntu 26.04, Linux 6.18.57-current-sunxi64, AArch64. These results apply to
this image and board; they are not a compatibility claim for every Armbian build.
Tests ran in a separate source checkout; the distribution's installed
armbian-config was not replaced. No boot overlay was enabled during these tests.

## Configuration

| Check | Observed result | Remaining scope |
|---|---|---|
| Source assembly and real CLI API | `bash tools/config-assemble.sh -p` succeeded; CPU, screen and DM status commands succeeded | Package installation/upgrade integration |
| CPU governor | `ondemand` → `schedutil` → restored | Workload/power/thermal measurements |
| CPU maximum frequency | 1416000 → 1008000 kHz, readback matched; invalid 999999999 rejected without changing settings | Durable boot policy is not implemented by this runtime-only module |
| Reboot | Boot ID changed; temporary schedutil/1008000 settings reset to ondemand/1416000 | User-selected persistent CPU profile |
| Display manager | LightDM configured and active; native reconfiguration of the installed LightDM succeeded; remained configured and active after reboot | Switching between different installed DMs was not tested |
| Display detection | HDMI-A-1 disconnected; LightDM greeter found, no ordinary local desktop session | Connected monitor, XFCE panel launch, mode change/revert and persistence |

CPU driver: `cpufreq-dt`; available frequencies in kHz:
480000, 720000, 936000, 1008000, 1104000, 1200000, 1320000, 1416000.
The existing cpufrequtils defaults file had ENABLE=false and no corresponding
service was installed. It was not used as evidence of an active persistent policy.

Reproduction from an assembled checkout:

```sh
sudo ./bin/armbian-config --api module_cpu_power status
sudo ./bin/armbian-config --api module_screen_settings status
sudo ./bin/armbian-config --api module_display_manager status
```

An unassembled checkout previously tried to source absent generated libraries
and emitted a cascade of errors. The entrypoint now checks those libraries and
menu data before elevation or module execution, and prints the assembly command.
CPU/display/source-checkout Bats regressions: 31 tests passed. They complement
the board tests; they do not substitute for a connected display.

## GPU rendering

Kernel driver: Panfrost, Mali-G31 MC1, render node `/dev/dri/renderD128`.
Installed Mesa: 26.0.8-1ubuntu0.3. Surfaceless EGL reported OpenGL ES 3.1
with renderer `Mali-G31 MC1 (Panfrost)`.

[`zero2w-gles-smoke.c`](zero2w-gles-smoke.c) rendered 100 alternating red/green
triangle frames and checked foreground/background pixels after readback. All
checks passed with the Panfrost renderer; the test rejects llvmpipe. This confirms
actual headless GPU rendering, not only driver enumeration. It is not an FPS
benchmark or proof of accelerated rendering in the user's XFCE session.

```sh
cc -Wall -Wextra -Werror tests/hardware/zero2w-gles-smoke.c \
  -lEGL -lGLESv2 -o /tmp/zero2w-gles-smoke
/tmp/zero2w-gles-smoke
```

Build dependencies: libegl-dev and libgles-dev. Do not compile assertion-based
acceptance tests with `-DNDEBUG`. Run with access to the render node.

Default `vulkaninfo --summary` exposed only the CPU llvmpipe device. A single
diagnostic invocation with `PAN_I_WANT_A_BROKEN_VULKAN_DRIVER=1` also enumerated
Mali-G31 via PanVK, API 1.0.335, conformance 0.0.0.0. That flag was not saved in
the environment. Experimental enumeration is not a successful Vulkan render or
game test. See the [Mesa Panfrost documentation](https://docs.mesa3d.org/drivers/panfrost.html)
for the driver and opt-in context; installed-version observations above take
precedence over capabilities of newer Mesa releases.

## Video decoding

Kernel driver: Cedrus at `1c0e000.video-codec`, V4L2 stateless interface.
GStreamer 1.28.2-1ubuntu1.2, FFmpeg 8.0.1. Each synthetic clip contained 60
320×240 frames at 30 fps. Explicit GStreamer decoder elements were used, so an
automatic software decoder fallback could not satisfy these tests.

| Format | Hardware decoder element | Frames | Mean squared byte error against software decode | Maximum byte difference |
|---|---|---:|---:|---:|
| H.264 | v4l2slh264dec | 60 | 0 | 0 |
| HEVC / H.265 | v4l2slh265dec | 60 | 0 | 0 |
| VP8 | v4l2slvp8dec | 60 | 0 | 0 |
| MPEG-2 | v4l2slmpeg2dec | 60 | 0.006507 | 3 |

Hardware and software outputs were converted to planar 8-bit I420, their exact
frame counts checked, and every output byte compared. MPEG-2 showed small
rounding differences. HEVC capability probing logged an unsupported extended
control, but its pipeline reached EOS and all decoded pixels matched. The
software x265 encoder also logged a NUMA affinity warning while creating its
input clip; it completed successfully.

[`zero2w-codec-smoke.sh`](zero2w-codec-smoke.sh) contains the tested pipelines and
comparisons, using a fresh temporary results directory on every invocation:

```sh
bash tests/hardware/zero2w-codec-smoke.sh /tmp
```

Requires FFmpeg with libx264/libx265/libvpx encoders, Python 3, GStreamer tools,
parsers/converters and the v4l2codecs plugin; access to the media/video nodes.
Each run retains approximately 54 MB of generated media and logs for inspection.
These are functional decoder tests, not 1080p/4K throughput, 10-bit profile,
zero-copy display, audio/video synchronization or browser/player acceptance.

## Remaining hardware acceptance

1. Connect HDMI and log into XFCE as an ordinary user. Check the native screen
   settings launch, resolution/refresh changes, revert and behavior after login
   and reboot. Confirm the desktop renderer, not merely headless EGL.
2. Exercise a chosen game or emulator and record renderer, resolution, frame
   pacing and temperature. Vulkan currently requires explicit experimental opt-in.
3. Test realistic video files in the intended player and resolution, including
   audio synchronization and sustained playback; keep decoder selection visible.
4. Hardware PWM remains a separate WiringPi task. Only software PWM/tone on
   physical 37-to-29 through 1 kOhm was tested. PWM1 on physical 32 was not enabled
   because the owner kept the existing wiring. GPIO loopback/IRQ test details
   belong to the WiringPi fork's H618 support document.

Native CVBS is a separate driver bring-up described in
[`zero2w-cvbs.md`](zero2w-cvbs.md); HDMI/GPU/Cedrus results do not validate TV-out.
