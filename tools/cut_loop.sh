#!/usr/bin/env bash
# Keeps cutting new clips from all sources in gta6/clips/stream-sources.json (run next to stream_loop.py --post-only).
cd "$(dirname "$0")/.." || exit 1
while true; do
  python3 -c 'import json;[print(s["key"], s["file"]) for s in json.load(open("gta6/clips/stream-sources.json"))]' |
  while read -r key file; do
    [ -e "$file" ] && python3 tools/stream_clips.py "$key" "$file" --max 8
  done
  sleep 60
done
