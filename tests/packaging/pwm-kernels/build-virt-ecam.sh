#!/bin/bash
# Test fixture for QEMU virt only. The vendor kernel includes PCI, XHCI and
# usb-storage, but its board config omits the generic ECAM platform driver.
set -euo pipefail
[[ $# == 3 ]] || { echo "Usage: $0 VENDOR_SOURCE PREPARED_HEADERS EMPTY_OUTPUT" >&2; exit 2; }
src=$(realpath "$1"); k=$(realpath "$2")
mkdir "$3"; work=$(realpath "$3")
cp "$src/drivers/pci/ecam.c" "$src/drivers/pci/controller/"pci-host-{common,generic}.c "$work/"
python3 - "$work/ecam.c" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
data=p.read_text()
old='conflict = request_resource_conflict(&iomem_resource, &cfg->res);\n\tif (conflict)'
if data.count(old)!=1:
    raise ValueError("Expected the pinned 6.6.98 ECAM implementation")
# Both APIs claim the range exclusively. Only the errno-returning wrapper
# is exported to modules by this kernel.
data=data.replace('\tstruct resource *conflict;\n','').replace(old,'if (request_resource(&iomem_resource, &cfg->res))')
start=data.index('\t\tdev_err(dev, "can\'t claim ECAM area')
end=data.index(';',start)
p.write_text(data[:start]+'\t\tdev_err(dev, "cannot reserve virtual ECAM window\\n")'+data[end:])
PY
cat > "$work/Makefile" <<'KBUILD'
obj-m := qa-ecam.o
qa-ecam-y := ecam.o pci-host-common.o pci-host-generic.o
ccflags-y += -DCONFIG_PCI_HOST_COMMON_MODULE=1
KBUILD
make -C "$k" -j2 ARCH=arm64 CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" M="$work" modules
