#!/usr/bin/env python3
"""Cut new stream clips and schedule them on TikTok, until --target posts are scheduled.

Sources come from gta6/clips/stream-sources.json: [{"key": "tomo", "file": "gta6/quelle/live/x.ts"}, ...]
Each clip gets its own TikTok schedule slot (every --every minutes). Log: gta6/kanal/stream-gepostet.log
Needs the visible Chrome on CDP port 9333 (see tools/tiktok.mjs) and PW_CORE in the environment.
"""
import argparse
import datetime as dt
import fcntl
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
HOLD = ROOT / "gta6" / "kanal" / "stream-unklar.log"   # unconfirmed/failed: never retried automatically


def posted():
    if not LOG.exists():
        return {}, None
    done, last = {}, None
    for line in LOG.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        cid, when = parts[0], parts[1]
        done[cid] = when
        last = max(last or when, when)
    if HOLD.exists():
        for line in HOLD.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                done.setdefault(parts[0], parts[1])
                if parts[1][:2] == "20":
                    last = max(last or parts[1], parts[1])
    return done, (dt.datetime.fromisoformat(last) if last else None)


def next_slot(last, every):
    soon = dt.datetime.now() + dt.timedelta(minutes=30)
    t = max(soon, last + dt.timedelta(minutes=every)) if last else soon
    t = t.replace(second=0, microsecond=0)
    step = every if every % 5 == 0 and 60 % every == 0 else 15
    rem = t.minute % step
    if rem:
        t += dt.timedelta(minutes=step - rem)
    return t


def tiktok(*args):
    env = dict(os.environ, AI_LABEL="0")
    try:
        r = subprocess.run(["node", str(ROOT / "tools" / "tiktok.mjs"), *args], capture_output=True, text=True,
                           env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return r.stdout + r.stderr


def hold(cid, when, why):
    with HOLD.open("a", encoding="utf-8") as f:
        f.write(f"{cid}\t{when}\t{why}\n")


def read_index():
    out = []
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--every", type=int, default=15, help="minutes between scheduled posts")
    ap.add_argument("--idle", type=int, default=240, help="seconds to wait when nothing is new")
    ap.add_argument("--now", action="store_true", help="publish immediately instead of scheduling")
    ap.add_argument("--gap", type=int, default=5, help="with --now: minimum minutes between posts")
    args = ap.parse_args()
    lock = open(ROOT / "gta6" / "kanal" / ".stream-loop.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("another stream_loop is already running")
    fails = {}
    while True:
        try:
            if step(args, fails):
                return
        except Exception as err:  # keep the loop alive
            print(f"loop error: {err}", flush=True)
            time.sleep(60)


def step(args, fails):
    if True:
        done, last = posted()
        if len(done) >= args.target:
            print(f"target reached: {len(done)} scheduled")
            return True
        sources = json.loads((CLIPS / "stream-sources.json").read_text())
        for s in sources:
            if (ROOT / s["file"]).exists():
                r = subprocess.run([sys.executable, str(ROOT / "tools" / "stream_clips.py"), s["key"],
                                    str(ROOT / s["file"]), "--max", "8"], capture_output=True, text=True)
                print(r.stdout.strip(), r.stderr.strip()[-300:], flush=True)
        clips = read_index()
        todo = [c for c in clips if c["id"] not in done and Path(c["file"]).exists()]
        # alternate streamers so the feed doesn't show the same face 5x in a row
        todo.sort(key=lambda c: (sum(1 for d in done if d.rsplit("-", 1)[0] == c["streamer"]), c["id"]))
        if not todo:
            time.sleep(args.idle)
            return False
        c = todo[0]
        if args.now:
            now = dt.datetime.now()
            past = [dt.datetime.fromisoformat(w) for w in done.values() if w[:2] == "20"]
            past = [w for w in past if w <= now]  # scheduled future posts don't count
            ref = max(past) if past else None
            wait = (ref + dt.timedelta(minutes=args.gap) - dt.datetime.now()).total_seconds() if ref else 0
            if wait > 0:
                time.sleep(min(wait, args.idle))
                return False
            slot = dt.datetime.now().replace(second=0, microsecond=0)
            out = tiktok("prepare", c["file"], c["caption"])
            return finish(c, slot, out, fails)
        slot = next_slot(last, args.every)
        if slot.month != dt.datetime.now().month:  # tiktok.mjs only picks days in the shown month
            print("slot is in next month, waiting", flush=True)
            time.sleep(args.idle)
            return False
        when = slot.strftime("%d %H:%M")
        out = tiktok("prepare", c["file"], c["caption"], when)
        return finish(c, slot, out, fails)


def finish(c, slot, out, fails):
    if True:
        print(out.strip()[-400:], flush=True)
        if "PREPARED" not in out:
            fails[c["id"]] = fails.get(c["id"], 0) + 1
            print(f"skip {c['id']}: prepare failed ({fails[c['id']]}x)", flush=True)
            if fails[c["id"]] >= 3:
                hold(c["id"], "FAILED", "prepare failed 3x")
            time.sleep(30)
            return False
        out = tiktok("post", c["caption"])
        print(out.strip()[-300:], flush=True)
        if "POSTED" in out:
            with LOG.open("a", encoding="utf-8") as f:
                f.write(f"{c['id']}\t{slot.isoformat(timespec='minutes')}\t{c['caption']}\n")
        elif "ABORT" in out:          # nothing was clicked: safe to retry later
            fails[c["id"]] = fails.get(c["id"], 0) + 1
            if fails[c["id"]] >= 3:
                hold(c["id"], "FAILED", "post aborted 3x")
            time.sleep(30)
        else:                          # may be scheduled already: never repost automatically
            hold(c["id"], slot.isoformat(timespec="minutes"), "UNCONFIRMED " + out.strip()[-80:].replace("\t", " "))
        return False


if __name__ == "__main__":
    main()
