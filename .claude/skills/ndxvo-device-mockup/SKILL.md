---
name: ndxvo-device-mockup
description: Use when the device preview in the NDXVO converter looks misaligned, when adjusting MOCKUP_SCREEN / MOCKUP_CROP / CORNER_RADIUS_RATIO / DEVICE_PANEL_ROTATION, or when replacing the embedded device photo (MOCKUP_B64, esp32.jpg). Explains the geometry and how to inspect it visually.
---

# Device mockup (preview composition)

## Pieces

| Constant | Meaning |
|---|---|
| `MOCKUP_B64` | Base64 JPEG of the 800x800 device photo (a re-encoded copy of `esp32.jpg`). Use `outline.py` for its line range and never print it. |
| `MOCKUP_SCREEN = (x, y, w, h)` | Active LCD area inside the 800x800 photo. `w/h` should be about 172/320 = 0.5375. |
| `MOCKUP_CROP = (left, top, right, bottom)` | A PIL crop **box**, not x,y,w,h: the part of the photo shown in the pane. |
| `CORNER_RADIUS_RATIO` | Rounded LCD corners as a fraction of the screen width. Used in the **preview only**; the encoded video is always a full rectangle. |
| `DEVICE_PANEL_ROTATION = 180` | The panel is mounted upside down. The file is pre-rotated (default `rotation = 180`, i.e. `hflip,vflip`), and the preview turns it back. |

`App._compose_device(frame)` builds the preview in four steps:
1. Rotate the 172x320 frame by `DEVICE_PANEL_ROTATION`.
2. Resize it with LANCZOS to `MOCKUP_SCREEN` w x h.
3. Paste it into a copy of the photo through the anti-aliased rounded mask (`_rounded_mask`, 4x supersampled).
4. Crop to `MOCKUP_CROP`.

The canvas size of the device pane is derived from `MOCKUP_CROP`.

## Inspect alignment visually

Run this from the repo root and write the output **outside** the repo; PNGs are
not git-ignored. Open the images with Read to look at them.

```python
import base64, io, os, tempfile, ndxvo_converter as n
from PIL import Image, ImageDraw
out = tempfile.mkdtemp(prefix="ndxvo-mockup-")
im = Image.open(io.BytesIO(base64.b64decode(n.MOCKUP_B64))).convert("RGB")
x, y, w, h = n.MOCKUP_SCREEN
d = ImageDraw.Draw(im)
d.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 0, 0))
d.rectangle(n.MOCKUP_CROP, outline=(0, 200, 255))
im.save(os.path.join(out, "overlay.png"))
for name, (cx, cy) in {"tl": (x, y), "tr": (x + w, y), "bl": (x, y + h), "br": (x + w, y + h)}.items():
    im.crop((cx - 24, cy - 24, cx + 24, cy + 24)).resize((288, 288), Image.NEAREST).save(os.path.join(out, "corner_%s.png" % name))
print(out, "aspect", round(w / h, 4), "target", round(172 / 320, 4))
```

Judge each corner crop: the red line should sit exactly on the LCD edge, not
on the bezel. Nudges are usually 1-3 px; a past commit was "Move device preview
screen 3 pixels to the left". After a change, keep `w/h` within about 0.5% of
0.5375 and keep `MOCKUP_SCREEN` inside `MOCKUP_CROP`.

To preview a real frame, extract one from an output AVI with
`ffmpeg -ss 1 -i out.avi -frames:v 1 frame.png`. Then repeat steps 1-4 above,
or run the app and load the source.

## Replacing the device photo

1. Prepare an 800x800 photo (or update the geometry for another size). Save it
   as JPEG at about quality 90; the current blob is about 26 KB of base64.
2. Do **not** paste base64 through the Edit tool. Write a one-off Python script
   that base64-encodes the file, splits it into the same `    "....."` string
   lines, and replaces the lines between `MOCKUP_B64 = (` and the closing `)`.
   `outline.py` prints that range.
3. Re-measure `MOCKUP_SCREEN`, `MOCKUP_CROP` and `CORNER_RADIUS_RATIO` with the
   overlay above.
4. Update `esp32.jpg` and the README "Adjusting the device mockup" block so all three agree.

## Known drift (2026-10-11)

The README shows `MOCKUP_SCREEN = (297, 227, 207, 385)`, but the code has
`(294, 227, 207, 385)`, after the 3 px move. The README needs updating;
ndxvo-docs-drift covers this.
