---
name: ndxvo-project-map
description: Start here for any analysis, review, question or change in the NDXVO ESP32 converter repo. Maps the files, the sections and data flow of the single-file app, the design invariants that must not break, and routes to the specialised ndxvo-* skills. Includes outline.py, which navigates ndxvo_converter.py without reading its embedded base64 photo.
---

# NDXVO converter - project map

## What this repo is

A single-file Tkinter GUI (`ndxvo_converter.py`) that turns any video or still
into a 172 x 320 MJPEG-in-AVI clip, or a single baseline JPEG, that an ESP32
board shows from an SD card. It generalises this reference command:

    ffmpeg -y -i input5.mp4 -an -pix_fmt yuvj420p -c:v mjpeg -q:v 2 -vf "fps=30,scale=-2:320:flags=lanczos,crop=172:320:(in_w-172)/2:0,hflip,vflip" video5.avi

The owner develops and tests on Windows; the end user runs it on a Mac. GitHub
Actions builds a macOS `.dmg` (arm64) and a Windows `.exe`, each with a static
ffmpeg inside. GUI text is English; the owner talks to Claude in Polish.

## Files

| Path | Role |
|---|---|
| `ndxvo_converter.py` | The whole app: constants, ffmpeg helpers, probing, filter chain, preview thread, encoder thread, Tk GUI |
| `esp32.jpg` | Photo of the device; a re-encoded copy is embedded in the script as `MOCKUP_B64` |
| `README.md` | Run, build, release, filter-chain rationale, mockup geometry |
| `.github/workflows/build.yml` | preflight -> macos + windows (each: full, lite) -> release |
| `.github/scripts/resolve-version.sh` | picks and validates the version (form input or tag) |
| `.github/scripts/stamp_version.py` | rewrites the `APP_VERSION = "..."` line before packaging |
| `.github/scripts/build-ffmpeg-lite.sh` | compiles the minimal LGPL ffmpeg for the `-lite` variant (component lists live here) |
| `.github/scripts/smoke_test_ffmpeg.py` | runs the app's own probe/preview/export commands against a given ffmpeg |
| `.github/scripts/collect_licenses.py` | assembles the third-party license folder (GPL or LGPL ffmpeg, Pillow, Python) for each build |
| `licenses/` | notices template plus FFmpeg's license texts, copied verbatim from the source release |
| `.github/workflows/claude.yml` | `@claude` in issues / PRs |
| `tools/verify-ffmpeg-embedded.ps1` | local Windows proof that ffmpeg is inside the one-file exe |

## Reading ndxvo_converter.py efficiently

About 280 of its ~2000 lines are the base64 photo. Never Read the whole file.
Map it first, then pull exactly what you need (`python` on Windows, `python3`
on macOS/Linux; run from the repo root):

    python .claude/skills/ndxvo-project-map/scripts/outline.py                 # sections, classes, functions with line ranges
    python .claude/skills/ndxvo-project-map/scripts/outline.py --constants     # every UPPER_CASE constant and its value
    python .claude/skills/ndxvo-project-map/scripts/outline.py --show build_vf --show App._compose_device
    python .claude/skills/ndxvo-project-map/scripts/outline.py --refs schedule_preview   # every use, with enclosing function

`--refs` searches code only, not comments or strings; use Grep for those.

## Sections of the app, top to bottom

1. **Constants**: output size, frame budget, mockup geometry, quality table, fixed `PIX_FMT`, output formats, sharpen, `MOCKUP_B64`.
2. **Subprocess helpers**: `find_ffmpeg` (bundled `_MEIPASS` -> next to the script -> frozen exe dir / `.app` Resources -> PATH -> Homebrew paths), `run_capture`, `_no_window_kwargs` (no console flash on Windows).
3. **Media probing**: `probe` parses `ffmpeg -i` stderr (no ffprobe is shipped), the EXIF orientation table, `avi_frame_sizes` / `frame_budget_report`, quality and format helpers.
4. **Filter chain**: `Params`, `scaled_size`, `build_vf`, `build_generate_cmd`, `quote_cmd`.
5. **Preview renderer**: the `Renderer` thread; the newest job wins and the original frame is cached.
6. **Encoder**: the `Encoder` thread, with `-progress pipe:1` and cancel.
7. **GUI**: `App(tk.Tk)`, covering vars and traces, layout, mockup composition, parameter plumbing, the result pump and actions.

## Data flow

    Choose file -> load_file -> probe() -> MediaInfo (displayed w/h, duration, fps, is_image, EXIF orientation)
    Tk var traces -> _on_param_change -> schedule_preview (refreshes command box, 150 ms debounce)
      -> _fire_preview -> Renderer.submit(RenderJob(seq, info, params.copy(), t))
         Renderer thread: _extract_original  (ffmpeg -ss t, 1 frame, EXIF fix only, PNG)
                          _extract_processed (same build_vf without fps, same mjpeg / -q:v / -pix_fmt as export)
      -> results queue -> _poll_results (main thread, every 40 ms) -> _apply_render (drops stale seq)
      -> _compose_device (undo panel rotation, paste with rounded mask into the photo)
    Generate -> build_generate_cmd(info, p, out, at=timestamp) -> Encoder thread -> encode_progress / encode_done
      -> verify_output(out, p) -> AVI: frame_budget_report(out), warning if any frame exceeds FRAME_BUDGET_BYTES
                               JPEG: jpeg_frame_header(out) must be SOF0 (baseline), no size limit

## Invariants (check every change against these)

| # | Rule | Why |
|---|---|---|
| 1 | One file; stdlib + tkinter + Pillow only (ffmpeg external) | Owner requirement: trivial to run on a Mac; this is also why the photo is embedded |
| 2 | Output is locked to 172x320 MJPEG: an AVI with `-an`, or (`Params.out_format = "jpg"`) one baseline JPEG written with `-frames:v 1 -f image2 -update 1` | Anything else will not play on the device; JPEGDEC cannot decode progressive |
| 3 | For 0/180 rotation the orientation filters go last; for 90/270 the transpose goes first | Keeps the chain byte-identical to the reference command (lanczos before and after a flip differs) |
| 4 | When orientation runs last, crop offsets are sign-compensated | Crop sliders keep one meaning whatever the filter order |
| 5 | The intermediate scale size is computed in Python (`scaled_size`, `_even`), never `force_original_aspect_ratio` | Exact, readable geometry |
| 6 | Panel mounted upside down: `DEVICE_PANEL_ROTATION = 180`, default `rotation = 180` (= `hflip,vflip`) | Changing one without the other makes the preview disagree with the device |
| 7 | Stills: `-noautorotate` + `EXIF_FILTERS` first in the chain; `probe` swaps w/h for orientations 5-8 | Same behaviour on every ffmpeg build |
| 8 | Preview equals export: `_extract_processed` uses the same `build_vf`, codec, `-q:v` and `-pix_fmt` | The preview must show real MJPEG artefacts |
| 9 | Every frame must stay at or under `FRAME_BUDGET_BYTES` = 172*320*2/5 = 22016 B | The player silently skips larger frames (black screen); see ndxvo-frame-budget |
| 10 | `APP_VERSION = "<value>"` stays one line in exactly that form | CI rewrites it (`stamp_version.py`) |
| 11 | Worker threads never touch Tk; they only post to `self.results` | Tk is not thread-safe |
| 12 | Python 3.9+ syntax; subprocesses on Windows use `_no_window_kwargs()` | Supported runtimes; no console flashes |
| 13 | Chroma is always `PIX_FMT = "yuvj420p"`; never offer 4:2:2 / 4:4:4 | JPEGDEC assumes Cb/Cr 1x1, ffmpeg writes them 1x2: decode error on the device (see ndxvo-frame-budget) |

## Adding or changing a user parameter: the plumbing checklist

A new knob has to appear in all of these places, or it silently does nothing in
some path:
- `Params.__init__`
- `App._build_vars` (variable and trace)
- `App._build_controls` (widget)
- `App._collect_params`
- `App.on_reset`
- `App._update_enabled_state` (when it applies only in some modes)
- `build_vf` / `build_generate_cmd`
- `Renderer._extract_processed` (when it changes encoder flags)
- README (see ndxvo-docs-drift)

## Code review checklist

- All invariants above still hold.
- Any new `subprocess.Popen` with both stdout and stderr on PIPE drains both.
  `Encoder.run` reads stderr only after stdout reaches EOF, so a very chatty
  ffmpeg (more than 64 KB of stderr) could block it. Keep ffmpeg's stderr small
  or read it on a separate thread.
- UI state changes happen in the main thread.
- New GUI text is English.

## Which skill for what

| Task | Skill |
|---|---|
| What command does the app emit; rotation, crop, fit or EXIF bugs; refactoring `build_vf` | ndxvo-filter-chain |
| Will this file play on the device; black frames; "Invalid image file"; quality and chroma | ndxvo-frame-budget |
| Preview mockup misaligned, corner radius, replacing the device photo | ndxvo-device-mockup |
| GitHub Actions, versions, releases, `.dmg` / `.exe`, Gatekeeper | ndxvo-build-pipeline |
| Is the README still true? | ndxvo-docs-drift |

When reporting an analysis, list failures first, then risks, then what was
verified, and say which ffmpeg version the observations came from.
