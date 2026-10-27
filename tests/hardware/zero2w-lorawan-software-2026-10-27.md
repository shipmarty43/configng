# LoRaWAN software checkpoint — 2026-10-27

The Orange Pi was **powered off by the user**. All work here was performed on
the development host; no SSH, GPIO toggling, RF transmission, modem access or
deployment to the board took place. The optional component is disabled by default.

## Implementation

See [build, configuration and runtime contract](../../hardware/lorawan/README.md).
The native service uses RadioLib for EU433 / OTAA-1.0.4 / Class A, and the existing
WiringPi H618 backend for GPIO. It adds private credentials, persistent session
state, write-ahead nonce reservation, a shared radio lock and systemd integration.
The configurator menu/API exposes check/status/start/stop through a separate
module. It does not install overlays, provision keys or enable autostart.

Dependency revisions:

- RadioLib `3b1d917bbacba0062dd7064c1157893ef9c6384e`, version field 7.8.1.
- WiringPi `f627770e5a0ae10331e39ef5694ee3928b136897` / H618 fork.
- Host compiler GNU C++ 15.2.0, x86-64; OpenSSL 3.5.5.

## Checks performed

| Check | Result | Boundary |
|---|---|---|
| Native CMake build | Passed | Host binary, not AArch64 deployment |
| CTest persistence/configuration | Passed, 34 assertions | Real RadioLib serialization with synthetic state; no successful radio join simulated |
| CTest CLI | Passed | Actual binary, private temporary files; config, provision, status, disabled run, symlinks, permissions and corrupt-state refusal |
| CTest HAL | Passed | Link-time GPIO doubles; pin restrictions, errors, edge callbacks, cancellation and cleanup |
| All three CTest suites with AddressSanitizer/UndefinedBehaviorSanitizer | Passed | `ASAN_OPTIONS=detect_leaks=0`; no leak-check claim |
| LoRaWAN Bats module tests | 8 passed | Mocked service calls, no system services started |
| Shell syntax, JSON parse, diff whitespace | Passed | Source checks |
| `bash tools/config-assemble.sh -p` | Passed | Combined configurator and menu generated locally |
| Staged CMake install | Passed | Files placed under a temporary DESTDIR; nothing installed on host/board |
| systemd unit verification | Passed with temporary ExecStart pointing at the built binary | Original `/usr/local/bin/opi-lorawan` intentionally absent on host; unrelated existing host-unit warnings retained outside this repo |

Persistence tests cover an unused live nonce versus its durable reservation,
restoring a reserved nonce after interruption, exhausting DevNonce without wrap,
retaining uplink/downlink counters in a clean session, dropping the session on
interruption, and rejoining before uplink-counter wrap. Corrupt/incompatible state
never becomes an automatic fresh identity. Real sudden-power-loss behavior of
the SD card and gateway session state still require hardware tests.

Reproduce the native/CLI/HAL suites with the CMake/CTest commands in the component
README. Reproduce the configurator tests with:

```sh
bats tests/bats/lorawan.bats
```

For a sanitizer build use a separate CMake build directory and add
`-DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer'` and
`-DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'`. Build, then run
`ASAN_OPTIONS=detect_leaks=0 ctest --test-dir BUILD_DIRECTORY --output-on-failure`.

## Remaining hardware gates

1. Verify the actual HAT revision, SPI controller and software-CS route, RESET,
   BUSY, DIO1, antenna switch and crystal configuration. No overlay has been
   applied or claimed working by this change.
2. Build/install on AArch64 and observe ownership/cleanup against kernel drivers.
3. Join a real EU433 gateway/network server and validate RX1/RX2, confirmations,
   ADR, channel changes and long-payload behavior under load.
4. Test clean restarts and abrupt power loss with retained nonces/counters and
   conservative cooldown. Verify the host clock after a battery-only boot.
5. Add actual UPS/GNSS telemetry encoders and application-facing messaging APIs
   after the basic packet path is qualified. The current payload is an explicitly
   configured test byte string; received bytes are logged, never executed.

Python GPIO bindings, Meshtastic and Reticulum integrations remain separate work.
This checkpoint does not mark the complete radio ecosystem or LoRaWAN hardware
support finished.
