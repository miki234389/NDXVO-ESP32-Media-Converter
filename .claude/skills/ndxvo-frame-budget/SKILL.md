---
name: ndxvo-frame-budget
description: Use when asking whether an AVI produced by the NDXVO converter will play on the ESP32 device, when the device shows black or frozen frames, or when choosing Quality / Colour (chroma) / Sharpen settings. Explains the player's per-frame buffer limit, the levers that change frame size, and how to measure a file.
---

# Frame budget (will it play on the device?)

## The constraint

The player on the ESP32 allocates one frame buffer of
`width * height * 2 / 5` bytes and **silently skips** any MJPEG frame larger
than that. In the app this is `FRAME_BUDGET_BYTES = 172*320*2//5 = 22016` bytes.
Oversized frames show up as black or frozen frames, not as an error.

After Generate, the app runs `frame_budget_report(out)`, which returns
`(oversized, total, largest)` and warns when `oversized > 0`.

The decoder on the device is JPEGDEC:
- **Supported**: baseline JPEG with chroma sampling 0x11, 0x21, 0x12 and 0x22 (4:4:4, 4:2:2, 4:4:0, 4:2:0).
- **Not supported**: progressive JPEG.

ffmpeg's `mjpeg` encoder emits baseline, so this is fine unless someone changes the codec.

## Levers, biggest effect first

1. **Content.** Noise, foliage, water and small text are expensive; flat
   graphics are cheap. Measure on the user's real footage, not on a test pattern.
2. **Colour (chroma, `-pix_fmt`).** 4:4:4 is the largest, then 4:2:2 (the
   current default), then 4:2:0 (the reference command).
3. **Quality dial.** Levels 1..10 map to `-q:v` values 24,16,12,9,7,5,4,3,2,1.
   Level 9 is `-q:v 2` (the default); level 10 (`-q:v 1`) is the most likely to
   overflow.
4. **Sharpen** adds high-frequency detail and therefore bytes.
5. **FPS** does **not** change the size of each frame; it only changes the total file size.

## Measure a finished file

From Python at the repo root (uses the app's own parser):

```python
import ndxvo_converter as n
print(n.frame_budget_report("video5.avi"))   # (oversized, total, largest)
```

With ffprobe (a full ffmpeg install on the dev machine; ffprobe is not bundled with the app):

    ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt,r_frame_rate -of default=nw=1 video5.avi
    ffprobe -v error -select_streams v:0 -show_entries packet=size -of csv=p=0 video5.avi > sizes.txt

To summarise `sizes.txt`:
- **macOS / Linux**: `awk '{n++; if($1>22016)o++; if($1>m)m=$1} END{print n" frames, "o+0" over budget, max "m}' sizes.txt`
- **PowerShell**: `$s = Get-Content sizes.txt | % {[int]$_}; "$($s.Count) frames, $(($s | ? {$_ -gt 22016}).Count) over budget, max $(($s | Measure -Max).Maximum)"`

The expected stream is `mjpeg`, 172x320, the chosen `yuvj4xxp`, `30/1` or `25/1`, and no audio stream.

## Choose settings for a specific source

Encode a short, representative excerpt at several settings and compare the
largest frame. Use the app's real command from the "ffmpeg command" box, with
`-ss <t>` before `-i` and `-t 3` after it. Report the results as a table:

| Quality (q:v) | 4:2:0 max | 4:2:2 max | 4:4:4 max |
|---|---|---|---|

Mark each cell as a percentage of 22016 and flag anything over 100%.
Recommend the highest setting that keeps a safety margin of about 10%, because
other scenes may be busier than the excerpt.

## Caveats to check when relevant

- **Long clips.** ffmpeg switches to OpenDML (extra `AVIX` RIFF chunks) above
  about 1 GB, which is roughly 25-30 minutes at these sizes. `avi_frame_sizes`
  reads only the first RIFF, so the in-app report would undercount. Whether the
  device player reads `AVIX` is unverified.
- **Budget formula.** The player's buffer formula is taken from the comment in
  the code. If the firmware changes, update `FRAME_BUDGET_BYTES` and README together.
