---
name: ndxvo-filter-chain
description: Use when analysing, debugging or changing how the NDXVO converter builds its ffmpeg command - rotation, mirroring, crop/stretch/fit, crop offsets, EXIF orientation of photos, scale sizes, sharpen, quality and chroma flags, still-image clips, or parity with the original reference command. Explains scaled_size / build_vf / build_generate_cmd and how to verify them.
---

# Filter chain (ffmpeg command generation)

Code lives in the "Filter chain" section of `ndxvo_converter.py`. Pull it with:

    python .claude/skills/ndxvo-project-map/scripts/outline.py --show scaled_size --show build_vf --show build_generate_cmd --show Renderer._extract_processed

## Chain order emitted by build_vf

    [EXIF filters, stills only] -> fps=N (videos only)
    -> [transpose + mirrors, only for 90/270]
    -> scale=W:H:flags=lanczos
    -> crop=172:320:x:y  | pad=172:320:x:y:0xRRGGBB  (skipped when already 172x320; nothing for stretch)
    -> unsharp=3:3:A:3:3:0  (only when sharpen > 0; luma only)
    -> [hflip / vflip, only for 0/180]

- **Rotation 180** is emitted as `hflip,vflip`, XOR-ed with Mirror H and Mirror V.
  For example, 180 with Mirror H gives just `vflip`. Rotation 90 is `transpose=1`
  and 270 is `transpose=2`, followed by any mirrors.
- **Orientation last for 0/180** keeps the default output byte-identical to the
  reference command. A 90/270 turn swaps the axes, so it runs first, and
  `scaled_size` gets the swapped source dimensions.
- **Crop offsets** run from -1 to +1. They map to
  `x = round((sw-172)/2 * (1+crop_x))`, clamped to `[0, sw-172]` (same for y).
  When orientation runs last, `crop_x` is negated for each horizontal flip and
  `crop_y` for each vertical one. The offsets therefore always refer to the
  oriented picture, the one written to the file.
- **scaled_size**:
  - `stretch` gives 172x320.
  - `crop` covers the frame: the binding side is set exactly and the other side becomes `_even(...)`, never smaller than the target.
  - `fit` contains the frame and pads, centred, with the pad colour.
- **EXIF** (stills): the input is read with `-noautorotate`, then `EXIF_FILTERS`
  applies the canonical turn:

  | Tag | Filters |
  |---|---|
  | 2 | hflip |
  | 3 | hflip,vflip |
  | 4 | vflip |
  | 5 | transpose=0 (true transpose) |
  | 6 | transpose=1 (clockwise) |
  | 7 | transpose=3 (anti-transpose) |
  | 8 | transpose=2 (counter-clockwise) |

  `probe` swaps the reported width and height for tags 5-8, so all geometry
  works on the displayed size.
- **Stills** use `-loop 1 -framerate <fps> -noautorotate -i img -t <duration>`,
  with no `fps` filter.
- **Quality dial**: levels 1..10 map through
  `QUALITY_QSCALE = (24,16,12,9,7,5,4,3,2,1)`; level 9 is `-q:v 2`, as in the
  reference. Chroma is passed as `-pix_fmt` (`yuvj420p` / `yuvj422p` / `yuvj444p`).
- **Preview vs export**: `_extract_processed` calls `build_vf(..., include_fps=False)`
  and must pass the same `-pix_fmt`, `-c:v mjpeg` and `-q:v` as `build_generate_cmd`.
  When you change one, change the other.

## Print the command for any configuration (no GUI)

On Windows and macOS (tkinter present), run this from the repo root:

```python
import ndxvo_converter as n
info = n.MediaInfo("in.mp4"); info.ok = True
info.width, info.height, info.duration, info.fps = 1920, 1080, 10.0, 30.0
p = n.Params()              # edit: p.rotation, p.fit, p.crop_x, p.mirror_h, p.chroma, p.quality, p.sharpen ...
print(n.build_vf(p, info))
print(n.quote_cmd(n.build_generate_cmd(info, p, "out.avi")))
```

For a still, set `info.is_image = True` and `info.orientation = <EXIF tag>`, with
width and height already swapped for tags 5-8. On headless Linux without
tkinter, register stub modules first:

```python
import sys, types
tk = types.ModuleType("tkinter"); tk.Tk = type("Tk", (), {}); tk.TclError = Exception
sys.modules["tkinter"] = tk
for s in ("ttk", "filedialog", "messagebox", "colorchooser"):
    m = types.ModuleType("tkinter." + s); setattr(tk, s, m); sys.modules["tkinter." + s] = m
```

The known-good baseline is a 1920x1080 video with defaults, which gives
`fps=30,scale=568:320:flags=lanczos,crop=172:320:198:0,hflip,vflip`.

## Verify against real ffmpeg

- **Output geometry**: run the emitted `-vf` on a synthetic source and look for `s:172x320` in the showinfo line:

      ffmpeg -hide_banner -f lavfi -i "testsrc2=s=1921x1080:r=30:d=1,format=rgb24" -vf "<vf>,showinfo" -frames:v 1 -f null -

  Keep `format=rgb24`. Without it the lavfi source rounds odd sizes down, which hides odd-size bugs.
- **Byte identity with the reference**:
  1. Make a source: `ffmpeg -f lavfi -i testsrc2=s=1920x1080:r=30:d=2 -c:v ffv1 src.mkv`.
  2. Run the reference command and the app's command with `p.chroma = "yuvj420p"`, quality 9 and other defaults.
  3. Compare hashes (`certutil -hashfile a.avi SHA256` on Windows, `shasum -a 256` on macOS).

  Different ffmpeg versions encode differently, so compare outputs from one binary only.

## Known findings (2026-10-11, ffmpeg 4.4; re-check before relying on them)

- **`_even` vs ffmpeg's `-2`**: `_even` uses Python's banker's `round()`, while
  ffmpeg rounds half up. They differ when `src_w*320/src_h/2` is exactly an
  even number plus 0.5:

  | Source | `_even` | ffmpeg `-2` |
  |---|---|---|
  | 569x320 | 568 | 570 |
  | 573x320 | 572 | 574 |

  Common sources (1920x1080, 1280x720, 1080x1920, 3840x2160) are unaffected,
  and the output stays a valid 172x320. A fix that matches ffmpeg is
  `int(math.floor(value / 2.0 + 0.5)) * 2`.
- **Defaults no longer match the reference**: they now use 4:2:2 chroma
  (`CHROMA_DEFAULT = "yuvj422p"`). Byte identity needs Colour set to 4:2:0.

## Change checklist

- Cover rotations 0, 90, 180 and 270, each with and without Mirror H and Mirror V.
- Cover the crop, stretch and fit modes, with crop offsets -1, 0 and +1.
- Cover landscape, portrait, square and extreme sources, plus stills with EXIF tags 1, 3, 6 and 8.
- The output is always 172x320.
- The crop and pad offsets stay in bounds.
- The 1920x1080 baseline string above is unchanged.
- The preview and the export still use the same flags.
