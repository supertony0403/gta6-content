#!/usr/bin/env bash
# Renders original GTA 6 countdown Shorts (1080x1920, 7 s) from own graphics only:
# no Rockstar assets, no third-party music. Output: gta6/clips/countdown-<label>.mp4
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=gta6/clips
FONT="$HOME/.local/share/fonts/lyrics/Anton-Regular.ttf"
SUB="$HOME/.local/share/fonts/lyrics/BebasNeue-Regular.ttf"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

render() { # label big line1 line2
  local label=$1 big=$2 l1=$3 l2=$4 dst="$OUT/${PREFIX:-countdown}-$1.mp4"
  [ -e "$dst" ] && { echo "skip (exists): $dst"; return; }
  printf '%s' "$big" > "$TMP/big.txt"; printf '%s' "$l1" > "$TMP/l1.txt"; printf '%s' "$l2" > "$TMP/l2.txt"
  printf '%s' "19.11.2026 · PS5 & Xbox Series X|S" > "$TMP/l3.txt"
  printf '%s' "Kein offizieller Rockstar-Kanal" > "$TMP/l4.txt"
  local fade="alpha='min(1,max(0,(t-%s)/0.5))'"
  ffmpeg -v error -y \
    -f lavfi -i "gradients=s=1080x1920:r=30:c0=0xff2d95:c1=0x7b2ff7:c2=0x00e5ff:c3=0x1a0033:n=4:speed=0.015:d=7" \
    -f lavfi -i "anullsrc=r=48000:cl=stereo" -t 7 \
    -filter_complex "[0:v]drawbox=c=black@0.35:t=fill,
      drawtext=fontfile=$SUB:textfile=$TMP/l1.txt:fontsize=120:fontcolor=white:x=(w-tw)/2:y=330:$(printf "$fade" 0.2),
      drawtext=fontfile=$FONT:textfile=$TMP/big.txt:fontsize=620:fontcolor=white:borderw=14:bordercolor=0xff2d95:x=(w-tw)/2:y=(h-th)/2-80:$(printf "$fade" 0.6),
      drawtext=fontfile=$SUB:textfile=$TMP/l2.txt:fontsize=130:fontcolor=0x00e5ff:x=(w-tw)/2:y=1230:$(printf "$fade" 1.2),
      drawtext=fontfile=$SUB:textfile=$TMP/l3.txt:fontsize=70:fontcolor=white:x=(w-tw)/2:y=1380:$(printf "$fade" 1.8),
      drawtext=fontfile=$SUB:textfile=$TMP/l4.txt:fontsize=44:fontcolor=white@0.7:x=(w-tw)/2:y=1470,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]" \
    -map "[v]" -map 1:a -c:v libx264 -preset medium -crf 18 -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
    -c:a aac -shortest -movflags +faststart "$TMP/out.mp4"
  mv -f "$TMP/out.mp4" "$dst"
  echo "ok: $dst"
}

render 5tage "5" "NOCH" "TAGE BIS GTA 6"
render 4tage "4" "NOCH" "TAGE BIS GTA 6"
render 3tage "3" "NOCH" "TAGE BIS GTA 6"
render 2tage "2" "NOCH" "TAGE BIS GTA 6"
render 1tag  "1" "NOCH" "TAG BIS GTA 6"
render heute "0" "ES IST SOWEIT" "GTA 6 IST DA"

# Fact shorts: only facts consistently reported for Rockstar's announcements (checked 14.11.2026)
PREFIX=fakt
render 1-ort     "VC"  "ZURÜCK NACH"  "VICE CITY IN LEONIDA"
render 2-duo     "2"   "ZWEI HAUPTFIGUREN" "JASON & LUCIA"
render 3-konsole "PS5" "ZUM START AUF" "UND XBOX SERIES X|S"
render 4-pc      "PC?" "UND DER"      "NOCH KEIN TERMIN"
