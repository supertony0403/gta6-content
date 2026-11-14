#!/usr/bin/env python3
"""Adds ElevenLabs voiceovers to rendered shorts.

Reads gta6/clips/voiceover.json, synthesizes one MP3 per short (cached in
gta6/clips/vo/), then writes <name>-vo.mp4: the original short with its last
frame held until the voiceover has ended plus a short tail.
Requires ELEVENLABS_API_KEY in the environment.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "gta6" / "clips"
VO_DIR = CLIPS / "vo"
TAIL = 1.0  # seconds of picture after the voice ends
DELAY = 0.3  # seconds of silence before the voice starts
SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35}
API = "https://api.elevenlabs.io"


def api(path, key, payload=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def voice_id(name, key):
    voices = json.loads(api("/v2/voices?page_size=100", key))["voices"]
    for v in voices:
        if v["name"] == name:
            return v["voice_id"]
    sys.exit(f"Voice not found: {name}")


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out)


def main():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY missing")
    cfg = json.loads((CLIPS / "voiceover.json").read_text(encoding="utf-8"))
    VO_DIR.mkdir(exist_ok=True)
    vid = None
    settings = cfg.get("settings", SETTINGS)
    for name, text in cfg["texte"].items():
        src, dst = CLIPS / f"{name}.mp4", CLIPS / f"{name}-vo.mp4"
        tag = hashlib.sha256(json.dumps([text, cfg["voice"], cfg["model"], settings],
                                        ensure_ascii=False).encode()).hexdigest()[:10]
        mp3 = VO_DIR / f"{name}-{tag}.mp3"
        if not src.exists():
            print(f"skip (no video): {name}")
            continue
        if dst.exists() and mp3.exists() and dst.stat().st_mtime >= mp3.stat().st_mtime:
            print(f"skip (up to date): {dst.name}")
            continue
        if not mp3.exists():
            vid = vid or voice_id(cfg["voice"], key)
            audio = api(f"/v1/text-to-speech/{vid}?output_format=mp3_44100_128", key,
                        {"text": text, "model_id": cfg["model"],
                         "voice_settings": settings})
            if len(audio) < 1000:
                print(f"error: empty TTS response for {name}")
                continue
            tmp = mp3.with_suffix(".part")
            tmp.write_bytes(audio)
            tmp.rename(mp3)
        total = max(duration(src), DELAY + duration(mp3) + TAIL)
        hold = max(0.0, total - duration(src))
        tmp = dst.with_name(dst.stem + ".part.mp4")
        try:
            subprocess.run(
              ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(mp3),
               "-filter_complex",
               f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f}[v];"
               f"[1:a]adelay={int(DELAY * 1000)}:all=1,apad,atrim=0:{total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11,"
               f"aresample=48000[a]",
               "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", str(tmp)],
              check=True,
            )
        except subprocess.CalledProcessError as err:
            tmp.unlink(missing_ok=True)
            print(f"error: ffmpeg failed for {name}: {err}")
            continue
        tmp.replace(dst)
        print(f"ok: {dst.name} ({total:.1f}s)")


if __name__ == "__main__":
    main()
