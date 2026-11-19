#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Exercise both TV enum values as seen by modetest, including NTSC = 0.
set -eu
probe=$(CDPATH= cd -- "$(dirname "$0")/../probe" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PATH="$tmp:$PATH" LIST="$tmp/resources"
cat > "$tmp/modetest" <<'END'
#!/bin/sh
if [ "$4" = -c ]; then cat "$LIST"; else printf '<%s>\n' "$@"; fi
END
chmod +x "$tmp/modetest"
cat > "$LIST" <<'END'
Connectors:
51 0 connected Composite-1 0x0 2 50
  #0 720x576i 50.00
  #1 720x480i 59.94
  16 TV mode:
    enums: NTSC=0 PAL=3
    value: 3
CRTCs:
43 0 (0,0) (0x0)
Planes:
32 0 0 0,0 0,0 0 0x00000001
  formats: XR24
  8 type:
    value: 0
33 0 0 0,0 0,0 0 0x00000001
  formats: XR24
  8 type:
    value: 1
END
for standard in NTSC PAL; do
	case "$standard" in
	NTSC) index=1; height=480; value=0 ;;
	PAL) index=0; height=576; value=3 ;;
	esac
	actual=$("$probe/cvbs-bars" "$standard")
	expect=$(printf '<%s>\n' -M sun4i-drm -a -s "51@43:#$index" -P "33@43:720x$height+0+0@XR24" -F smpte -w "51:TV mode:$value")
	[ "$actual" = "$expect" ] || { echo "Invalid $standard modeset" >&2; exit 1; }
done
sed -i 's/ NTSC=0//' "$LIST"
if "$probe/cvbs-bars" NTSC >/dev/null 2>&1; then
	echo 'Accepted a missing NTSC property' >&2
	exit 1
fi
echo 'PASS PAL and NTSC modeset arguments, absent standard rejected'
