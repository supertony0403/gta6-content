#!/usr/bin/env python3
"""Cut new stream clips and schedule them on TikTok, until --target posts are scheduled.

Sources come from gta6/clips/stream-sources.json: [{"key": "tomo", "file": "gta6/quelle/live/x.ts"}, ...]
Each clip gets its own TikTok schedule slot (every --every minutes). Log: gta6/kanal/stream-gepostet.log
Needs the visible Chrome on CDP port 9333 (see tools/tiktok.mjs) and PW_CORE in the environment.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "gta6" / "clips"
INDEX = CLIPS / "stream-clips.jsonl"
LOG = ROOT / "gta6" / "kanal" / "stream-gepostet.log"


def posted():
    if not LOG.exists():
        return {}, None
    done, last = {}, None
    for line in LOG.read_text(encoding="utf-8").splitlines():
        cid, when, _ = line.split("\t", 2)
        done[cid] = when
        last = max(last or when, when)
    return done, (dt.datetime.fromisoformat(last) if last else None)


def next_slot(last, every):
    soon = dt.datetime.now() + dt.timedelta(minutes=20)
    t = max(soon, last + dt.timedelta(minutes=every)) if last else soon
    t = t.replace(second=0, microsecond=0)
    step = every if 60 % every == 0 else 15
    rem = t.minute % step
    if rem:
        t += dt.timedelta(minutes=step - rem)
    return t


def tiktok(*args):
    env = dict(os.environ, AI_LABEL="0")
    r = subprocess.run(["node", str(ROOT / "tools" / "tiktok.mjs"), *args], capture_output=True, text=True,
                       env=env, timeout=600)
    return r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--every", type=int, default=15, help="minutes between scheduled posts")
    ap.add_argument("--idle", type=int, default=240, help="seconds to wait when nothing is new")
    args = ap.parse_args()
    while True:
        done, last = posted()
        if len(done) >= args.target:
            print(f"target reached: {len(done)} scheduled")
            return
        sources = json.loads((CLIPS / "stream-sources.json").read_text())
        for s in sources:
            if (ROOT / s["file"]).exists():
                r = subprocess.run([sys.executable, str(ROOT / "tools" / "stream_clips.py"), s["key"],
                                    str(ROOT / s["file"]), "--max", "4"], capture_output=True, text=True)
                print(r.stdout.strip(), r.stderr.strip()[-300:], flush=True)
        clips = [json.loads(x) for x in INDEX.read_text(encoding="utf-8").splitlines()] if INDEX.exists() else []
        todo = [c for c in clips if c["id"] not in done and Path(c["file"]).exists()]
        # alternate streamers so the feed doesn't show the same face 5x in a row
        todo.sort(key=lambda c: (sum(1 for d in done if d.startswith(c["streamer"])), c["id"]))
        if not todo:
            time.sleep(args.idle)
            continue
        c = todo[0]
        slot = next_slot(last, args.every)
        when = slot.strftime("%d %H:%M")
        out = tiktok("prepare", c["file"], c["caption"], when)
        print(out.strip()[-400:], flush=True)
        if "PREPARED" not in out:
            print(f"skip {c['id']}: prepare failed", flush=True)
            time.sleep(30)
            continue
        out = tiktok("post", c["caption"])
        print(out.strip()[-300:], flush=True)
        if "POSTED" in out:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(f"{c['id']}\t{slot.isoformat(timespec='minutes')}\t{c['caption']}\n")
        else:
            time.sleep(30)


if __name__ == "__main__":
    main()
