#!/bin/bash
# Manual integration fixture for XFCE 4.20.1 on the single-HDMI Zero 2W setup.
# Not a generic display configuration backend. Run as the logged-in user.
set -euo pipefail
profile=OpiValidation20261027
q() { xfconf-query -c displays "$@"; }
setprop() { q -p "$1" -n -t "$2" -s "$3"; }
case "${1:-}" in
 prepare)
  [[ $EUID != 0 && ${DISPLAY:-} == :0 ]] || exit 1
  [[ $(xrandr --current | awk '/ connected/ {n++} END {print n}') == 1 ]] || exit 1
  xrandr --current | grep -q '^HDMI-1 connected 1024x600' || exit 1
  # This fixture only accepts the exact original three-property configuration.
  [[ $(q -l | wc -l) == 3 && $(q -p /ActiveProfile) == Default && $(q -p /AutoEnableProfiles) == 3 && $(q -p /Notify) == 1 ]] || exit 1
  destination="$HOME/.local/state/opi-display-validation-20261027"
  mkdir -p "$destination"
  [[ ! -e "$destination/displays-original.xml" ]] || exit 1
  cp -p "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml" "$destination/displays-original.xml"
  edid=$(python3 - <<'PY'
from pathlib import Path
import hashlib
paths=list(Path('/sys/class/drm').glob('card*-HDMI-A-*/edid'))
valid=[p.read_bytes() for p in paths if p.read_bytes()]
assert len(valid)==1 and len(valid[0])>=128
print(hashlib.sha1(valid[0][:128]).hexdigest())
PY
)
  setprop "/$profile" string 'OPi validation 800x450'
  setprop "/$profile/HDMI-1" string HDMI-1
  setprop "/$profile/HDMI-1/Active" bool true
  setprop "/$profile/HDMI-1/EDID" string "$edid"
  setprop "/$profile/HDMI-1/Resolution" string 800x450
  setprop "/$profile/HDMI-1/RefreshRate" double 60.05
  setprop "/$profile/HDMI-1/Rotation" int 0
  setprop "/$profile/HDMI-1/Reflection" string 0
  setprop "/$profile/HDMI-1/Primary" bool true
  setprop "/$profile/HDMI-1/Scale" double 1.0
  setprop "/$profile/HDMI-1/Position/X" int 0
  setprop "/$profile/HDMI-1/Position/Y" int 0
  setprop /Schemes/Apply string "$profile"
  ;;
 inspect)
  q -p /ActiveProfile
  q -p "/$profile/HDMI-1/Resolution"
  xrandr --current
  ;;
 cleanup)
  q -p "/$profile" -r -R || true
  q -p /ActiveProfile -s Default
  xrandr --output HDMI-1 --mode 1024x600 --noprimary
  q -lv
  xrandr --current
  ;;
 *) echo 'Usage: zero2w-xfce-profile.sh prepare|inspect|cleanup' >&2; exit 2 ;;
esac
