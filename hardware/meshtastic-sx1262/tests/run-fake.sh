#!/usr/bin/env bash
# Run from the board with the prepared, sealed profile already installed.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
work=$(mktemp -d /var/tmp/opi-sx1262-fixture.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
python=/opt/opi-mesh/venv/bin/python
route=$(PYTHONPATH=/opt/opi-mesh "$python" -c 'import sx1262_profile as p; r=p.check(); print(r.spi, f"gpiochip{r.chip}")')
read -r spi gpio <<< "$route"
cc -shared -fPIC -O1 -Wall -Wextra -Werror -I "${GPIOD_INCLUDE:-/usr/include}" \
    "$source_dir/fake_bus.c" -Wl,-z,defs -l:libgpiod.so.3 -o "$work/bus.so"
touch "$work/spi" "$work/gpio"
systemd-run --quiet --wait --collect --pipe -p PrivateDevices=yes -p PrivateNetwork=yes \
    -p DevicePolicy=closed -p PrivateTmp=yes -p CapabilityBoundingSet= -p NoNewPrivileges=yes \
    -p ProtectSystem=strict -p ProtectKernelTunables=yes -p ProtectHome=yes -p LimitCORE=0 \
    -p MemoryMax=160M -p TasksMax=48 -p RuntimeMaxSec=90 \
    -p "BindReadOnlyPaths=$work/spi:/dev/$spi $work/gpio:/dev/$gpio $work/bus.so:/run/opi-mock-bus.so $source_dir/check_fake_bus.py:/run/opi-mock-check.py" \
    --setenv=PYTHONPATH=/opt/opi-mesh "$python" -u /run/opi-mock-check.py /run/opi-mock-bus.so
