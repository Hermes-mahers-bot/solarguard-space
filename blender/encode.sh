#!/usr/bin/env bash
# SolarGuard Space - encode rendered frames into shipping web assets.
#
#   ./encode.sh                # all three sequences
#   ./encode.sh turntable      # just one
#
# Produces:
#   assets/<seq>.mp4                     h264 / yuv420p / faststart
#   assets/<seq>.webp                    looping webp preview
#   assets/<seq>.gif                     looping gif preview
#   public/assets/hero/<seq>/001.jpg .. 1280x720 q82 scroll-scrub frames
set -euo pipefail

ROOT=/home/hermes2/solarguard-space
FF=/usr/bin/ffmpeg
FP=/usr/bin/ffprobe
FPS=24
CRF=20
QSCALE=5          # mjpeg quality: ~q85, keeps each 1280x720 frame < 120 KB

declare -A N=( [turntable]=96 [dustwave]=96 [clean]=60 )

seqs=("$@")
if [ ${#seqs[@]} -eq 0 ]; then seqs=(turntable dustwave clean); fi

mkdir -p "$ROOT/assets"

for seq in "${seqs[@]}"; do
  n=${N[$seq]}
  frames="$ROOT/renders/$seq/frames"
  have=$(ls "$frames" 2>/dev/null | grep -c '\.png$' || true)
  echo "=== $seq : $have/$n frames present ==="
  if [ "$have" -lt "$n" ]; then
    echo "!! $seq incomplete ($have/$n) - skipping"; continue
  fi

  echo "--- $seq mp4 ---"
  "$FF" -y -hide_banner -loglevel error -framerate $FPS -start_number 1 \
        -i "$frames/%04d.png" -frames:v $n \
        -c:v libx264 -preset slow -crf $CRF -pix_fmt yuv420p \
        -movflags +faststart "$ROOT/assets/$seq.mp4"

  echo "--- $seq webp ---"
  "$FF" -y -hide_banner -loglevel error -framerate $FPS -start_number 1 \
        -i "$frames/%04d.png" -vf "fps=12,scale=640:-2:flags=lanczos" \
        -frames:v $((n/2)) -loop 0 -c:v libwebp -lossless 0 -q:v 60 \
        "$ROOT/assets/$seq.webp"

  echo "--- $seq gif ---"
  "$FF" -y -hide_banner -loglevel error -framerate $FPS -start_number 1 \
        -i "$frames/%04d.png" \
        -vf "fps=12,scale=560:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" \
        -frames:v $((n/2)) "$ROOT/assets/$seq.gif"

  echo "--- $seq scroll-scrub jpegs ---"
  out="$ROOT/public/assets/hero/$seq"
  rm -rf "$out"; mkdir -p "$out"
  "$FF" -y -hide_banner -loglevel error -i "$ROOT/assets/$seq.mp4" \
        -vf "scale=1280:720:flags=lanczos" -q:v $QSCALE \
        "$out/%03d.jpg"
  echo "    $(ls "$out" | wc -l) jpgs, max $(du -b "$out"/*.jpg | sort -n | tail -1 | cut -f1) bytes"
done

echo
echo "=== verify ==="
for seq in "${seqs[@]}"; do
  f="$ROOT/assets/$seq.mp4"
  [ -f "$f" ] || continue
  printf "%s: " "$seq"
  "$FP" -v error -select_streams v:0 -count_frames -show_entries \
        stream=nb_read_frames,width,height,codec_name,pix_fmt \
        -of csv=p=0 "$f"
done
