#!/usr/bin/env python3
"""Run the converter's own ffmpeg commands against the ffmpeg about to be bundled.

The lite build is configured component by component, so a missing demuxer,
decoder or filter would otherwise surface only when a user opens a file. This
script makes CI hit it first. It generates a four-colour PNG, the same picture
as a JPEG with an EXIF quarter turn, and an MJPEG AVI clip exported from the
PNG. Each input then goes through probe, both preview renders and the AVI and
JPEG exports, with the converter's command builders unchanged and with two
settings: the reference command, and one that emits every other filter.

Every export must pass verify_output. On top of that, the reference export of
the PNG must show each colour where the half turn puts it, which catches a
build that writes valid but garbled pictures. Usage:

    python .github/scripts/smoke_test_ffmpeg.py vendor/ffmpeg
"""

import os
import queue
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import ndxvo_converter as n  # noqa: E402
from PIL import Image  # noqa: E402

SRC_W, SRC_H = 1200, 900
TOP_LEFT, TOP_RIGHT = (220, 40, 40), (40, 200, 40)
BOTTOM_LEFT, BOTTOM_RIGHT = (40, 60, 220), (230, 210, 40)
# Rotation 180 is hflip+vflip, so every quadrant of the source lands diagonally
# opposite in the 172x320 output. Points sit well clear of the seams, where
# lanczos ringing and 16x16 chroma blocks blur the colours.
EXPECTED = (
    ((43, 80), BOTTOM_RIGHT), ((128, 80), BOTTOM_LEFT),
    ((43, 240), TOP_RIGHT), ((128, 240), TOP_LEFT),
)
TOLERANCE = 16  # per channel; a correct encode at quality 9 is off by 2-3


def fail(message):
    sys.exit("error: " + message)


def settings():
    reference = n.Params()
    reference.rotation = 180          # the reference command's hflip,vflip
    reference.fit = "crop"
    reference.duration = 1.0
    busy = n.Params()                 # transpose, mirror, pad, unsharp, 25 fps
    busy.rotation = 90
    busy.mirror_h = True
    busy.fit = "fit"
    busy.pad_color = "#204080"
    busy.sharpen = 0.8
    busy.quality = 5
    busy.fps = 25
    busy.duration = 1.0
    return (("reference", reference), ("busy", busy))


def make_inputs(work):
    img = Image.new("RGB", (SRC_W, SRC_H))
    half_w, half_h = SRC_W // 2, SRC_H // 2
    img.paste(TOP_LEFT, (0, 0, half_w, half_h))
    img.paste(TOP_RIGHT, (half_w, 0, SRC_W, half_h))
    img.paste(BOTTOM_LEFT, (0, half_h, half_w, SRC_H))
    img.paste(BOTTOM_RIGHT, (half_w, half_h, SRC_W, SRC_H))
    png = os.path.join(work, "quadrants.png")
    img.save(png)
    jpg = os.path.join(work, "quadrants_exif6.jpg")
    exif = Image.Exif()
    exif[274] = 6
    img.save(jpg, quality=92, exif=exif)
    return png, jpg


def run(cmd, what):
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        fail("%s exited with %d\n  %s\n%s" % (what, proc.returncode, n.quote_cmd(cmd), tail))


def check_colours(path):
    with Image.open(path) as im:
        frame = im.convert("RGB")
    for (x, y), want in EXPECTED:
        box = frame.crop((x - 7, y - 7, x + 8, y + 8)).resize((1, 1), Image.BOX)
        got = box.getpixel((0, 0))
        if max(abs(a - b) for a, b in zip(got, want)) > TOLERANCE:
            fail("%s: pixel (%d, %d) is %s, expected about %s - this ffmpeg garbles "
                 "the picture" % (os.path.basename(path), x, y, got, want))


def exercise(path, work, renderer):
    info = n.probe(path)
    if not info.ok:
        fail("probe of %s: %s" % (os.path.basename(path), info.error))
    at = 0.0 if info.is_image else 0.5
    stem = os.path.splitext(os.path.basename(path))[0]
    outputs = {}
    for name, params in settings():
        what = "%s / %s" % (stem, name)
        job = n.RenderJob(1, info, params, at)
        renderer._orig_cache_key = None
        try:
            renderer._extract_original(job)
            frame = renderer._extract_processed(job)
        except RuntimeError as exc:
            fail("%s preview: %s" % (what, exc))
        if frame.size != (n.OUT_W, n.OUT_H):
            fail("%s preview is %dx%d" % ((what,) + frame.size))
        for fmt in ("avi", "jpg"):
            p = params.copy()
            p.out_format = fmt
            out = os.path.join(work, "%s_%s.%s" % (stem, name, fmt))
            run(n.build_generate_cmd(info, p, out, at), "%s %s export" % (what, fmt))
            problems = n.verify_output(out, p)
            if problems:
                fail("%s %s export: %s" % (what, fmt, "; ".join(problems)))
            outputs[(name, fmt)] = out
    print("ok  %s (%s)" % (info.summary, info.codec))
    return outputs


def main():
    if len(sys.argv) != 2:
        fail("usage: smoke_test_ffmpeg.py <ffmpeg binary>")
    n.FFMPEG = os.path.abspath(sys.argv[1])
    ok, version, problem = n.ffmpeg_identity(n.FFMPEG)
    if not ok:
        fail("%s is not usable: %s" % (n.FFMPEG, problem))
    print("ffmpeg %s at %s" % (version, n.FFMPEG))

    renderer = n.Renderer(queue.Queue())  # never started; its methods run inline
    with tempfile.TemporaryDirectory() as work:
        png, jpg = make_inputs(work)
        from_png = exercise(png, work, renderer)
        check_colours(from_png[("reference", "jpg")])
        exercise(jpg, work, renderer)
        # The PNG's reference export doubles as a video input: AVI demuxer,
        # MJPEG decoding, seeking and the fps filter.
        exercise(from_png[("reference", "avi")], work, renderer)
    print("ffmpeg handles every command the converter issues.")


if __name__ == "__main__":
    main()
