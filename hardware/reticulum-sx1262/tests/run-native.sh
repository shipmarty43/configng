#!/usr/bin/env bash
set -euo pipefail
tests=$(cd -- "$(dirname -- "$0")" && pwd)
fixture="$tests/../../meshtastic-sx1262/tests/fake_bus.c"
work=$(mktemp -d /var/tmp/opi-rnode-io.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
python=/opt/opi-mesh/venv/bin/python
read -r spi gpio hz <<< "$(PYTHONPATH=/opt/opi-mesh "$python" -c 'from rnode_adapter import checked_route; r,h=checked_route(); print(r.spi,f"gpiochip{r.chip}",h)')"
cc -shared -fPIC -O1 -Wall -Wextra -Werror -I "${GPIOD_INCLUDE:-/usr/include}" \
    "$fixture" -Wl,-z,defs -l:libgpiod.so.3 -o "$work/bus.so"
touch "$work/spi" "$work/gpio"
systemd-run --quiet --collect --wait --pipe -p PrivateDevices=yes -p DevicePolicy=closed \
    -p PrivateNetwork=yes -p PrivateTmp=yes -p CapabilityBoundingSet= -p NoNewPrivileges=yes \
    -p ProtectSystem=strict -p ProtectHome=yes -p LimitCORE=0 -p MemoryMax=128M -p RuntimeMaxSec=40 \
    -p "BindPaths=$work/spi:/dev/$spi" \
    -p "BindReadOnlyPaths=$work/gpio:/dev/$gpio $work/bus.so:/run/opi-rnode-bus.so $tests/check_native_bus.py:/run/opi-rnode-test.py" \
    --setenv=OPI_FIXTURE_SPI="/dev/$spi" --setenv=OPI_FIXTURE_GPIO="/dev/$gpio" --setenv=OPI_FIXTURE_HZ="$hz" \
    --setenv=PYTHONPATH=/opt/opi-mesh --setenv=LD_PRELOAD=/run/opi-rnode-bus.so \
    "$python" -u /run/opi-rnode-test.py
