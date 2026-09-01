# NDXVO ESP32 File Converter

A single-file GUI that turns any video or still image into an MJPEG-AVI clip an
ESP32 device with a 172 × 320 panel can play straight from an SD card.

It is a graphical superset of this command:

```
ffmpeg -y -i input5.mp4 -an -pix_fmt yuvj420p -c:v mjpeg -q:v 2 \
  -vf "fps=30,scale=-2:320:flags=lanczos,crop=172:320:(in_w-172)/2:0,hflip,vflip" \
  video5.avi
```

With the default settings the app emits a **byte-for-byte identical file** to
that command (verified against the same ffmpeg build — different ffmpeg versions
encode slightly differently, which is expected).

---

## Features

- Live device preview — the processed frame is composited into a photo of the
  actual panel, so you see what the hardware will show.
- The original frame is displayed next to it for comparison.
- Every parameter change re-renders the preview through **the same ffmpeg filter
  chain used for the export**, so the preview shows real MJPEG artefacts rather
  than an approximation.
- Timeline with `−0.5 s` / `+0.5 s` buttons and a scrubber to pick the frame.
- Fit modes: **Crop** (fill and trim, with X/Y framing sliders), **Stretch**,
  **Fit** (letterbox with a configurable pad colour).
- Rotation in 90° steps plus independent horizontal / vertical mirroring.
- Still images become clips of a configurable length.
- The exact ffmpeg command is always shown and can be copied.
- Output resolution is locked to 172 × 320 MJPEG/AVI, so you cannot accidentally
  produce a file the device will not play. FPS (30 / 25) and JPEG quality remain
  adjustable.

---

## Running from source

Requires Python 3.9+ and Pillow. ffmpeg must be installed, or sitting next to
the script.

```
pip install pillow
python ndxvo_converter.py
```

ffmpeg is located in this order: bundled inside the packaged app → next to the
script → on `PATH` → the usual Homebrew locations.

- Windows: `winget install Gyan.FFmpeg`
- macOS: `brew install ffmpeg`

You can also pass a file on the command line: `python ndxvo_converter.py clip.mp4`

---

## Building the binaries

Every build carries an explicit version. There are three ways to run it.

**Test build** — Actions → **Build** → **Run workflow**. Fill in `version`, leave
`release` unticked. You get artifacts on the run page; no tag, no Release. Use
this while iterating.

**Release from the button** — same form, but tick `release`. On success the
workflow tags the built commit as `v<version>` and publishes a GitHub Release
with both binaries attached. This is the normal way to cut a release: one field
and one checkbox, no local tagging.

**Release from a tag** — push `v1.2.0` yourself and the same thing happens, with
the version taken from the tag name.

Accepted format is `MAJOR.MINOR.PATCH` with an optional pre-release suffix —
`1.0.0`, `2.1.3`, `1.4.0-rc1`, `1.4.0-beta.2`. Anything else fails the build
immediately with a clear message, rather than producing a mislabelled binary.

The version is written into `APP_VERSION` in the source before packaging, shown
in the app's title bar, embedded in the artifact filenames, and (on macOS)
written into `CFBundleShortVersionString` so Finder's Get Info reports it. A run
straight from source reports `1.0.0-dev`, so an unpackaged build is never
mistaken for a release.

### Job layout

```
preflight ──┬── macos ───┐
            └── windows ─┴── release   (only if this run publishes)
```

`preflight` resolves and validates the version once and hands it to both build
jobs, so the two binaries can never disagree about what they are. When the run
is going to publish, it also checks up front that the tag is still free — that
failure arrives in seconds rather than after a full build.

`release` runs only after **both** builds succeed, so a tag never points at a
version that failed to build on one platform.

The tag is pushed with `GITHUB_TOKEN`, and GitHub deliberately does not start new
workflow runs for such pushes. That is what stops the tag-push trigger from
firing a second, duplicate build.

| Target | Runner | Output |
|---|---|---|
| macOS, Apple Silicon | `macos-14` (arm64) | `NDXVO-ESP32-File-Converter-<version>-macOS-arm64.dmg` |
| Windows x64 | `windows-latest` | `NDXVO-ESP32-File-Converter-<version>-Windows-x64.exe` |

Each target bundles a static ffmpeg, so end users install nothing. ffmpeg is
staged into `vendor/` and finished binaries into `out/`, so the upload globs
cannot pick up build inputs by accident.

Artifacts are uploaded with `archive: false`, so the download is the `.dmg` or
`.exe` itself rather than a zip wrapping it. This works because each job
produces exactly one file — if a build ever emits more than one, the upload
step fails rather than silently re-zipping.

Artifacts on a test build are kept for 90 days and need a GitHub login to
download. Release assets are permanent and directly linkable.

### First launch on macOS

The build is **ad-hoc signed but not notarised**, so Gatekeeper will refuse to
open it the first time, usually claiming the app "is damaged". It is not. Clear
the quarantine flag once:

```
xattr -dr com.apple.quarantine "/Applications/NDXVO ESP32 File Converter.app"
```

After that it opens normally, including after updates.

To remove this step entirely you need an Apple Developer ID ($99/year) and a
notarisation step in the workflow. The workflow is structured so that adding it
later is a matter of supplying the certificate and credentials as repository
secrets — no restructuring required.

---

## How the filter chain is built

Order: `fps` → `scale` → `crop`/`pad` → rotation and mirroring.

Orientation filters are placed **last** whenever they preserve the frame's
aspect ratio (rotation 0° or 180°), because lanczos resampling before a flip and
after a flip differ in the last floating-point bit — putting them last is what
makes the output byte-identical to the hand-written reference command. A 90° or
270° rotation swaps width and height, so it has to run first; the scale target
is computed against the already-rotated dimensions.

When the orientation filters run last, the crop offsets are sign-compensated, so
the framing sliders always move the crop window in the direction you see on the
preview.

Intermediate scale dimensions are computed in Python rather than left to
`force_original_aspect_ratio`, which rounds differently than `scale=-2:320`
(569 vs 568 px on a 1920 × 1080 source). This keeps the emitted command readable
and the geometry exact.

---

## Adjusting the device mockup

The panel photo is embedded in the script as base64. Two constants near the top
control where the preview is pasted:

```python
MOCKUP_SCREEN       = (297, 227, 207, 385)   # x, y, w, h of the active LCD area
MOCKUP_CROP         = (255, 165, 545, 635)   # visible region of the photo
CORNER_RADIUS_RATIO = 0.086                  # of the screen width
```

`MOCKUP_SCREEN` has an aspect ratio of 0.5377, matching 172 : 320. Its position
and the corner radius were measured against a reference photo of the panel
displaying a real UI.

The rounded corners are a property of the panel, so they are applied to the
**preview only** — the encoded video is always a full 172 x 320 rectangle.
