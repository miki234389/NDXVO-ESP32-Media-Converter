---
name: ndxvo-frame-budget
description: Use when asking whether an AVI or JPEG produced by the NDXVO converter will play on the ESP32 device, when the device shows black or frozen frames or "Invalid image file", or when choosing Quality / Sharpen settings or questioning the fixed 4:2:0 chroma. Explains the player's per-frame buffer limit, the levers that change frame size, and how to measure a file.
---

# Frame budget (will it play on the device?)

## The constraint

The player on the ESP32 allocates one frame buffer of
`width * height * 2 / 5` bytes and **silently skips** any MJPEG frame larger
than that. In the app this is `FRAME_BUDGET_BYTES = 172*320*2//5 = 22016` bytes.
Oversized frames show up as black or frozen frames, not as an error.

After Generate, the app runs `frame_budget_report(out)`, which returns
`(oversized, total, largest)` and warns when `oversized > 0`.

This limit applies to AVIs only. A single JPEG (Format: Image) is decoded
straight from the card, not through this buffer, so it has no size limit; a
large or busy one only takes longer to draw (confirmed by the owner, 2026-10-11).

The decoder on the device is JPEGDEC, for AVI frames and JPEG images alike:
- It picks the MCU layout from the **luma (Y) sampling factors only** (0x11, 0x21, 0x12, 0x22)
  and **assumes Cb and Cr are 1x1**.
- **Not supported**: progressive JPEG.

ffmpeg's `mjpeg` encoder always gives luma two block rows per MCU
(`ff_mjpeg_init_hvsample`, hard-coded, no option), so:

| `-pix_fmt` | ffmpeg writes Y / Cb / Cr | JPEGDEC |
|---|---|---|
| yuvj420p | 2x2 / 1x1 / 1x1 | decodes |
| yuvj422p | 2x2 / 1x2 / 1x2 | treated as 4:2:0, JPEG_DECODE_ERROR ("Invalid image file") |
| yuvj444p | 1x2 / 1x2 / 1x2 | JPEG_DECODE_ERROR |

Reproduced by the owner on a PC build of JPEGDEC (2026-10-11). The app
therefore fixes `PIX_FMT = "yuvj420p"` (there is no Colour control), and
`verify_output` checks the layout via `jpeg_decoder_problems` (on the JPEG
file, or on the AVI's first frame).

## Levers, biggest effect first

1. **Content.** Noise, foliage, water and small text are expensive; flat
   graphics are cheap. Measure on the user's real footage, not on a test pattern.
2. **Quality dial.** Levels 1..10 map to `-q:v` values 24,16,12,9,7,5,4,3,2,1.
   Level 9 is `-q:v 2` (the default); level 10 (`-q:v 1`) is the most likely to
   overflow.
3. **Sharpen** adds high-frequency detail and therefore bytes.
4. **FPS** does **not** change the size of each frame; it only changes the total file size.

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

The expected stream is `mjpeg`, 172x320, `yuvj420p`, `30/1` or `25/1`, and no audio stream.

## Choose settings for a specific source

Encode a short, representative excerpt at several settings and compare the
largest frame. Use the app's real command from the "ffmpeg command" box, with
`-ss <t>` before `-i` and `-t 3` after it. Report the results as a table:

| Quality (q:v) | Sharpen 0 max | Sharpen 0.5 max | Sharpen 1.0 max |
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
