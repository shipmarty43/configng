#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Emit one git-apply patch for the already Armbian-patched 6.18 kernel tree.
set -eu
cd "$(dirname "$0")"
cat sun4i-h618-route.patch sun4i-de33-cvbs-color.patch
for file in h618-*.[ch] allwinner,sun50i-h618-tv-encoder.yaml; do
	case "$file" in
	*.yaml) target=Documentation/devicetree/bindings/display/$file ;;
	*) target=drivers/gpu/drm/sun4i/$file ;;
	esac
	printf 'diff --git a/%s b/%s\nnew file mode 100644\n' "$target" "$target"
	diff -u --label /dev/null --label "b/$target" /dev/null "$file" || [ "$?" = 1 ]
done
