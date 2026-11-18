#!/usr/bin/env python3
"""Finds loud moments in a (growing) stream recording and cuts 9:16 clips.

Only for streamers whose clipping campaign allows it (gta6/kampagnen.md).
Usage: stream_clips.py <streamer-key> <source.ts> [--max N]
Config: gta6/clips/streamer.json   State: gta6/clips/stream-state.json
Output: gta6/clips/stream/<key>-<nnn>.mp4 plus a line in stream-clips.jsonl
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "gta6" / "clips"
OUT = CLIPS / "stream"
STATE = CLIPS / "stream-state.json"
INDEX = CLIPS / "stream-clips.jsonl"
W, H, FG_H = 1080, 1920, 608
FG_Y = (H - FG_H) // 2
PRE, POST = 20.0, 10.0          # seconds before/after the loudness peak
MARGIN = 40.0                   # never touch the still-growing tail
MIN_GAP = 60.0                  # minimum distance between two picked peaks
PER_10MIN = 3                   # picks per 10 minutes of new material
SR = 16000


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def duration(src):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)])
    return float(out.stdout.decode().strip() or 0)


def audio(src, start, length):
    out = run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src),
               "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    return np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def peaks(samples, offset, count):
    """Loudest 1-second windows, relative to the window's own median (handles quiet/loud streams)."""
    hop = SR // 2
    n = len(samples) // hop
    if n < 10:
        return []
    rms = np.sqrt(np.mean(samples[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    smooth = np.convolve(db, np.ones(2) / 2, mode="same")
    floor = np.median(smooth)
    order = np.argsort(smooth)[::-1]
    picked = []
    for i in order:
        t = offset + i * 0.5
        if smooth[i] - floor < 8:            # must clearly stand out (shouting, explosion, laughing)
            break
        if all(abs(t - p) >= MIN_GAP for p, _ in picked):
            picked.append((t, float(smooth[i] - floor)))
        if len(picked) >= count:
            break
    return sorted(picked)


_model = None


def transcribe(wav_samples):
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)
    segs, info = _model.transcribe(wav_samples, vad_filter=True, word_timestamps=True)
    words = [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]
    return words, info.language


def chunks(words, size=4):
    """Group words into short subtitle lines (TikTok style)."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= size or w[2].endswith((".", "!", "?", ",")):
            out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
            cur = []
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return out


def ass_time(t):
    t = round(max(0.0, t), 2)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(path, hook, credit, subs, length):
    lines = [f"Dialogue: 0,{ass_time(0)},{ass_time(length)},Hook,,0,0,0,,{esc(hook)}",
             f"Dialogue: 0,{ass_time(0)},{ass_time(length)},Credit,,0,0,0,,{esc(credit)}"]
    for a, b, txt in subs:
        b = min(max(b, a + 0.4), length)
        if b > a:
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{esc(txt.upper())}")
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Anton,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,7,0,8,70,70,{FG_Y - 360},1
Style: Sub,Anton,80,&H0000E5FF,&H0000E5FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,6,0,8,80,80,{FG_Y + FG_H + 60},1
Style: Credit,Bebas Neue,40,&H00E0E0E0,&H00E0E0E0,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,2,80,80,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n", encoding="utf-8")


def render(src, start, length, ass, dst):
    tmp = dst.with_name(dst.stem + ".part.mp4")
    fc = (f"[0:v]split=2[a][b];"
          f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,"
          f"eq=brightness=-0.25:saturation=1.2[bg];"
          f"[b]scale={W}:{FG_H}[fg];"
          f"[bg][fg]overlay=0:{FG_Y},ass={ass.name},setsar=1,format=yuv420p[v];"
          f"[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    try:
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src),
             "-filter_complex", fc, "-map", "[v]", "-map", "[aout]", "-t", f"{length:.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", tmp.name], cwd=ass.parent)
    except subprocess.CalledProcessError as err:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(err.stderr.decode()[-400:]) from err
    tmp.replace(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("source")
    ap.add_argument("--max", type=int, default=6, help="max clips per run")
    args = ap.parse_args()
    cfg = json.loads((CLIPS / "streamer.json").read_text(encoding="utf-8"))[args.key]
    src = Path(args.source).resolve()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    st = state.setdefault(src.name, {"done_until": 0.0, "count": 0})
    total = duration(src)
    end = total - MARGIN
    begin = st["done_until"]
    if end - begin < 120:
        print(f"wait: only {max(0, end - begin):.0f}s new material in {src.name}")
        return
    span = min(end - begin, 1800.0)                  # at most 30 min per run
    want = min(args.max, max(1, round(span / 600 * PER_10MIN)))
    found = peaks(audio(src, begin, span), begin, want)
    OUT.mkdir(parents=True, exist_ok=True)
    made = 0
    for t, score in found:
        start = max(0.0, t - PRE)
        length = min(PRE + POST, total - start - 5)
        if length < 12:
            continue
        st["count"] += 1
        cid = f"{args.key}-{st['count']:03d}"
        dst = OUT / f"{cid}.mp4"
        words, lang = transcribe(audio(src, start, length))
        hooks = cfg["hooks"]
        hook = hooks[(st["count"] - 1) % len(hooks)]
        ass = OUT / f"{cid}.ass"
        write_ass(ass, hook, cfg["credit"], chunks(words), length)
        try:
            render(src, start, length, ass, dst)
        except RuntimeError as err:
            print(f"error: {cid}: {err}")
            continue
        text = " ".join(w[2] for w in words)
        caption = cfg["caption"].format(hook=hook)
        with INDEX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": cid, "file": str(dst), "streamer": args.key, "source": src.name,
                                "start": round(start, 1), "length": round(length, 1), "loud_db": round(score, 1),
                                "lang": lang, "transcript": text[:300], "caption": caption},
                               ensure_ascii=False) + "\n")
        made += 1
        print(f"ok: {cid} @{start:.0f}s (+{score:.1f} dB) {text[:60]!r}")
    st["done_until"] = begin + span
    STATE.write_text(json.dumps(state, indent=1))
    print(f"done: {made} clips, analysed {begin:.0f}-{begin + span:.0f}s of {total:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
