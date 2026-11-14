#!/usr/bin/env python3
"""Cuts 9:16 commentary clips from the official GTA VI Extended Look.

Rockstar allows clipping/reacting to the Extended Look with own commentary
(no raw reupload). Each clip therefore gets: the original scene centered on a
blurred fill, a hook line, an ElevenLabs German commentary at the start (with
the original audio ducked), German subtitles translated by us, and a credit.
Config: gta6/clips/el-clips.json. Output: gta6/clips/<id>.mp4
Requires ELEVENLABS_API_KEY in the environment.
"""
import hashlib
import json
import os
import re
import urllib.error
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voiceover import SETTINGS, api, duration, voice_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "gta6" / "clips"
VO_DIR = CLIPS / "vo"
W, H, FG_H = 1080, 1920, 608
FG_Y = (H - FG_H) // 2
VO_DELAY = 0.2
DUCK = 0.22
RENDER_VERSION = 2  # bump on any visual/audio change not captured by the ASS text


def secs(ts):
    m, s = ts.split(":")
    return int(m) * 60 + float(s)


def ass_time(t):
    t = round(max(0.0, t), 2)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(text):
    return (text.replace("\\", "").replace("{", "(").replace("}", ")")
            .replace("\r", "").replace("\n", r"\N"))


def build_ass(clip, credit, length, path):
    start = secs(clip["start"])
    subs = [(secs(t) - start, txt) for t, txt in clip["subs"]]
    lines = []
    for i, (t, txt) in enumerate(subs):
        end = subs[i + 1][0] if i + 1 < len(subs) else length
        end = min(end, t + 4.5, length)
        if end > t:
            lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(end)},Sub,,0,0,0,,{esc(txt)}")
    lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(length)},Hook,,0,0,0,,{esc(clip['hook'])}")
    lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(length)},Credit,,0,0,0,,{esc(credit)}")
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Anton,118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,7,0,8,70,70,{FG_Y - 330},1
Style: Sub,Anton,76,&H0000E5FF,&H0000E5FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,5,0,8,90,90,{FG_Y + FG_H + 40},1
Style: Credit,Bebas Neue,34,&H00C8C8C8,&H00C8C8C8,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,8,90,90,{FG_Y + FG_H + 250},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n", encoding="utf-8")


def main():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY missing")
    cfg = json.loads((CLIPS / "el-clips.json").read_text(encoding="utf-8"))
    src = ROOT / cfg["quelle"]
    VO_DIR.mkdir(exist_ok=True)
    only = set(sys.argv[1:])
    vid = None
    settings = cfg.get("settings", SETTINGS)
    for clip in cfg["clips"]:
        if only and clip["id"] not in only:
            continue
        if not re.fullmatch(r"[a-z0-9-]+", clip["id"]):
            print(f"error: invalid clip id {clip['id']!r}")
            continue
        dst = CLIPS / f"{clip['id']}.mp4"
        tag = hashlib.sha256(json.dumps([RENDER_VERSION, clip, cfg, settings, DUCK, VO_DELAY, W, H, FG_H],
                                        ensure_ascii=False).encode()).hexdigest()[:10]
        vo_tag = hashlib.sha256(json.dumps([clip["vo"], cfg["voice"], cfg["model"], settings],
                                           ensure_ascii=False).encode()).hexdigest()[:10]
        mp3 = VO_DIR / f"{clip['id']}-{vo_tag}.mp3"
        stamp = CLIPS / f".{clip['id']}.{tag}"
        if dst.exists() and stamp.exists():
            print(f"skip (up to date): {dst.name}")
            continue
        if not mp3.exists():
            vid = vid or voice_id(cfg["voice"], key)
            try:
                audio = api(f"/v1/text-to-speech/{vid}?output_format=mp3_44100_128", key,
                            {"text": clip["vo"], "model_id": cfg["model"], "voice_settings": settings})
            except (urllib.error.URLError, OSError) as err:
                print(f"error: TTS failed for {clip['id']}: {err}")
                continue
            if len(audio) < 1000:
                print(f"error: empty TTS response for {clip['id']}")
                continue
            mp3.with_suffix(".part").write_bytes(audio)
            mp3.with_suffix(".part").rename(mp3)
        start, length = secs(clip["start"]), secs(clip["end"]) - secs(clip["start"])
        vd = VO_DELAY + duration(mp3) + 0.2
        if vd > length:
            print(f"error: voiceover longer than clip for {clip['id']} ({vd:.1f}s > {length:.1f}s)")
            continue
        ass = CLIPS / f"{clip['id']}.ass"
        build_ass(clip, cfg["credit"], length, ass)
        tmp = dst.with_name(dst.stem + ".part.mp4")
        fc = (
            f"[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,"
            f"eq=brightness=-0.22:saturation=1.2[bg];"
            f"[b]scale={W}:{FG_H}[fg];"
            f"[bg][fg]overlay=0:{FG_Y},ass={ass.name},setsar=1,format=yuv420p[v];"
            f"[0:a]volume='{DUCK}+(1-{DUCK})*clip((t-{vd:.2f})/0.4,0,1)':eval=frame[orig];"
            f"[1:a]adelay={int(VO_DELAY * 1000)}:all=1,volume=1.6,apad[vo];"
            f"[orig][vo]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]"
        )
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                 "-i", str(src), "-i", str(mp3), "-filter_complex", fc,
                 "-map", "[v]", "-map", "[aout]", "-t", f"{length:.3f}",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", "30",
                 "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                 "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", tmp.name],
                check=True, cwd=CLIPS,
            )
        except subprocess.CalledProcessError as err:
            (CLIPS / tmp.name).unlink(missing_ok=True)
            print(f"error: ffmpeg failed for {clip['id']}: {err}")
            continue
        (CLIPS / tmp.name).replace(dst)
        for old in CLIPS.glob(f".{clip['id']}.*"):
            old.unlink()
        stamp.touch()
        print(f"ok: {dst.name} ({length:.1f}s)")


if __name__ == "__main__":
    main()
