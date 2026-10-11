#!/usr/bin/env python3
"""Assemble the ProofOfPost demo video from the real Playwright recording.

Pipeline: cut + speed-adjust segments -> generated title/end cards -> concat ->
measure segment offsets -> SRT + ASS subtitles -> burn subtitles + ambient audio
-> proof-of-post-demo.mp4. All footage is the actual recorded session; only the
consensus waits are time-compressed (stated in the subtitles).
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = next((HERE / "capture" / "video").glob("*.webm"))
WORK = HERE / "build"
OUT = HERE / "output"
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG = "0x0b1220"

# (name, src_in, src_out, speed)  — speed > 1 compresses real waiting time
SEGMENTS = [
    ("intro", None, None, None),          # generated card
    ("overview", 8.0, 16.0, 1.5),
    ("connect", 16.0, 20.0, 1.0),
    ("form", 20.0, 32.7, 2.5),
    ("submit", 32.7, 38.0, 1.0),
    ("submit_wait", 38.0, 103.4, 16.0),
    ("pending", 103.4, 108.5, 1.0),
    ("evaluate", 108.5, 113.0, 1.0),
    ("evaluate_wait", 113.0, 212.1, 20.0),
    ("verdict", 215.0, 224.9, 1.4),
    ("appeal", 224.9, 231.0, 1.25),
    ("appeal_wait", 231.0, 329.6, 24.0),
    ("appeal_result", 329.6, 335.0, 1.0),
    ("closing", 335.0, 339.0, 1.5),
    ("endcard", None, None, None),        # generated card
]
CARD_DUR = {"intro": 2.5, "endcard": 4.0}

# subtitles per segment: list of (rel_start, rel_end, text)
SUBS = {
    "intro": [(0.0, 2.5, "ProofOfPost — on-chain content-rule adjudication")],
    "overview": [
        (0.0, 2.6, "What if content rules could be enforced on-chain?"),
        (2.6, 5.4, "Post content, define natural-language rules, back it with a GEN bond."),
    ],
    "connect": [(0.2, 4.0, "Connect a studio-dev-only signer — the key stays in memory.")],
    "form": [(0.0, 5.2, "Submit content and define the rules it must satisfy.")],
    "submit": [(0.4, 5.3, "submit() locks the 1 GEN bond and creates a PENDING entry.")],
    "submit_wait": [(0.0, 4.1, "The write settles through validator consensus… (sped up 16x)")],
    "pending": [(0.0, 5.1, "FINALIZED — entry #2 sits in the registry as PENDING.")],
    "evaluate": [(0.0, 4.5, "evaluate() asks the validators to judge the content.")],
    "evaluate_wait": [(0.0, 5.0, "Each validator independently re-derives the verdict. (sped up 20x)")],
    "verdict": [
        (0.0, 3.4, "Settled verdict: COMPLIANT — all three rules satisfied."),
        (3.4, 7.1, "The contract refunds the bond to the submitter."),
    ],
    "appeal": [(0.0, 4.9, "appeal() re-opens consensus on a NON_COMPLIANT verdict (max 2).")],
    "appeal_wait": [(0.0, 4.1, "Appeal consensus… (sped up 24x)")],
    "appeal_result": [(0.0, 5.4, "Verdict stands: NON_COMPLIANT, appeals 1 — bond stays slashed.")],
    "closing": [(0.0, 2.7, "ProofOfPost explores verifiable content compliance with intelligent contracts.")],
    "endcard": [],
}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(map(str, cmd[:8]))}...\n{p.stderr[-1200:]}")


def dur_of(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def srt_ts(t):
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_ts(t):
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def card(name, lines):
    """Dark title/end card with drawtext layers."""
    out = WORK / f"{name}.mp4"
    d = CARD_DUR[name]
    vf_parts = []
    for i, (text, size, y, font, color) in enumerate(lines):
        vf_parts.append(
            f"drawtext=fontfile={font}:text='{text}':fontsize={size}:fontcolor={color}:x=(w-text_w)/2:y={y}"
        )
    vf = ",".join(vf_parts) + f",format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st={d-0.5}:d=0.5"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c={BG}:s=1920x1080:r=25:d={d}",
         "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-an", str(out)])
    return out


def cut(name, src_in, src_out, speed):
    out = WORK / f"{name}.mp4"
    d = src_out - src_in
    run(["ffmpeg", "-y", "-v", "error",
         "-ss", str(src_in), "-t", str(d), "-i", str(SRC),
         "-vf", f"setpts=(PTS-STARTPTS)/{speed},fps=25,format=yuv420p",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-an", str(out)])
    return out


# ---- 1. build all segments ---------------------------------------------------
print("building segments…")
files = []
for name, si, so, sp in SEGMENTS:
    if name == "intro":
        f = card("intro", [
            ("ProofOfPost", 96, "(h-text_h)/2-70", FONT_BOLD, "white"),
            ("On-chain content-rule adjudication with GenLayer", 42, "(h-text_h)/2+50", FONT_REG, "0xBFD3FF"),
        ])
    elif name == "endcard":
        f = card("endcard", [
            ("ProofOfPost", 76, "(h-text_h)/2-120", FONT_BOLD, "white"),
            ("github.com/richeroveis/proof-of-post", 44, "(h-text_h)/2-10", FONT_REG, "0xBFD3FF"),
            ("richeroveis.github.io/proof-of-post", 44, "(h-text_h)/2+55", FONT_REG, "0xBFD3FF"),
            ("RuleRegistry 0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b · studio-dev", 34, "(h-text_h)/2+140", FONT_REG, "0x8FA3C8"),
        ])
    else:
        f = cut(name, si, so, sp)
    files.append((name, f))

# ---- 2. concat ----------------------------------------------------------------
with open(WORK / "concat.txt", "w") as fh:
    for _, f in files:
        fh.write(f"file '{f}'\n")
merged = WORK / "merged.mp4"
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
     "-i", str(WORK / "concat.txt"), "-c", "copy", str(merged)])

# ---- 3. subtitle timings from measured segment durations ----------------------
offsets, t = {}, 0.0
for name, f in files:
    offsets[name] = t
    t += dur_of(f)
total = t
print(f"merged duration: {total:.2f}s")

srt_entries, ass_events = [], []
i = 1
for name, _ in files:
    for (rs, re_, text) in SUBS.get(name, []):
        s, e = offsets[name] + rs, offsets[name] + min(re_, total)
        srt_entries.append(f"{i}\n{srt_ts(s)} --> {srt_ts(e)}\n{text}\n")
        ass_events.append(f"Dialogue: 0,Default,,0,0,0,,{text}")
        i += 1
(OUT / "proof-of-post-subtitles.srt").write_text("\n".join(srt_entries), encoding="utf-8")

ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,40,&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,0,0,3,2,1,2,80,80,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
for name, _ in files:
    for (rs, re_, text) in SUBS.get(name, []):
        s, e = offsets[name] + rs, offsets[name] + min(re_, total)
        ass += f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Default,,0,0,0,,{text}\n"
ass_path = WORK / "subs.ass"
ass_path.write_text(ass, encoding="utf-8")

# ---- 4. restrained ambient audio bed (self-generated, royalty-free) -----------
audio = WORK / "bed.m4a"
run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
     f"aevalsrc=0.05*sin(2*PI*110*t)*(0.75+0.25*sin(2*PI*0.07*t))"
     f"+0.04*sin(2*PI*164.81*t)*(0.75+0.25*sin(2*PI*0.05*t))"
     f"+0.03*sin(2*PI*220*t)*(0.75+0.25*sin(2*PI*0.09*t)):s=44100:d={total:.2f}",
     "-af", f"lowpass=f=700,aecho=0.7:0.5:400:0.25,volume=6dB,afade=t=in:st=0:d=2.5,afade=t=out:st={total-3}:d=3",
     "-c:a", "aac", "-b:a", "160k", str(audio)])

# ---- 5. burn subtitles + audio -> final ---------------------------------------
final = OUT / "proof-of-post-demo.mp4"
run(["ffmpeg", "-y", "-v", "error", "-i", str(merged), "-i", str(audio),
     "-vf", f"ass={ass_path}",
     "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
     "-r", "25", "-c:a", "copy", "-shortest",
     "-movflags", "+faststart", str(final)])
print("final:", final)
