# NDXVO Media Converter

A single-file GUI that turns any video or still image into an MJPEG-AVI clip, or
a single JPEG, that an ESP32 device with a 172 × 320 panel shows straight from
an SD card.

It is a graphical superset of this command:

```
ffmpeg -y -i input5.mp4 -an -pix_fmt yuvj420p -c:v mjpeg -q:v 2 \
  -vf "fps=30,scale=-2:320:flags=lanczos,crop=172:320:(in_w-172)/2:0,hflip,vflip" \
  video5.avi
```

With the default settings the app emits a **byte-for-byte identical file** to
that command (verified against the same ffmpeg build — different ffmpeg versions
encode slightly differently, which is expected).

Saved as **Image (.jpg)**, the same chain runs on one frame. For a 4032 × 3024
photo with the default settings:

```
ffmpeg -y -noautorotate -i photo.jpg -frames:v 1 -pix_fmt yuvj420p -c:v mjpeg -q:v 2 \
  -vf "scale=426:320:flags=lanczos,crop=172:320:127:0,hflip,vflip" \
  -f image2 -update 1 photo_esp32.jpg
```

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
- **Format**: *Video (.avi)* or *Image (.jpg)*. A photo starts as a JPEG the
  device shows directly, or becomes a clip of a configurable length; a video
  starts as a clip, or saves the frame under the scrubber as a JPEG. The choice
  is remembered separately for photos and videos while the app is open.
- The exact ffmpeg command is always shown and can be copied.
- Output resolution is locked to 172 × 320, as MJPEG/AVI or baseline JPEG, so you
  cannot accidentally produce a file the device will not show. FPS (30 / 25, AVI
  only) and JPEG quality remain adjustable.
- Colour is fixed at 4:2:0 (`yuvj420p`). The device's decoder (JPEGDEC) reads
  the MCU layout from the luma channel alone and assumes the colour channels are
  1×1; ffmpeg writes 4:2:2 as Y 2×2 / Cb,Cr 1×2 and 4:4:4 as 1×2 throughout, so
  both fail to decode ("Invalid image file") in AVIs and JPEGs alike.
- Every export is read back before it is reported as done: an AVI must be MJPEG,
  tagged `MJPG`, 172 × 320, at the chosen FPS; a JPEG must be 172 × 320. Both
  must be baseline (the device cannot decode progressive) with the 4:2:0
  layout above (an AVI is checked on its first frame). The per-frame size limit is
  checked for AVIs only: the device decodes a JPEG straight from the card, so a
  large one just takes longer to draw. If a check fails, the app says exactly
  what is wrong and saves `<name>_report.txt` next to the file — app version,
  system, ffmpeg path and version, the exact command, and the full ffmpeg log —
  so a bad file can be diagnosed without anyone touching a terminal.
- The ffmpeg in use is always shown in its own row, with full path and version,
  and can be changed there (`Browse…`, or type a path; `Use built-in` goes back).
  A candidate is actually started and must have the MJPEG encoder before it is
  accepted.

---

## Running from source

Requires Python 3.9+ and Pillow. ffmpeg must be installed, or sitting next to
the script.

```
pip install pillow
python ndxvo_converter.py
```

From source, ffmpeg is looked up next to the script, then on `PATH`, then in the
usual Homebrew locations. The packaged app never does this: it uses only the
ffmpeg bundled inside it, so every user encodes with the same tested binary. If
that copy is missing, the app reports a damaged install rather than silently
picking up whatever ffmpeg the machine happens to have.

A different ffmpeg is used only when someone picks it in the ffmpeg row. That
choice is remembered in `settings.json` (macOS: `~/Library/Application
Support/NDXVO Media Converter/`, Windows: `%APPDATA%\NDXVO Media Converter\`);
if it later stops working, the app says so and returns to the built-in one.

- Windows: `winget install Gyan.FFmpeg`
- macOS: `brew install ffmpeg`

You can also pass a file on the command line: `python ndxvo_converter.py clip.mp4`

On Windows, double-click `run.bat` instead. It finds Python (a `.venv` in the
project first, then `py`, then `python`), installs Pillow if it is missing, and
starts the app without a console window. To open a clip straight away, drag it
onto `run.bat`.

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
| macOS, Apple Silicon | `macos-14` (arm64) | `NDXVO-Media-Converter-<version>-macOS-arm64.dmg` |
| Windows x64 | `windows-latest` | `NDXVO-Media-Converter-<version>-Windows-x64.exe` |

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
xattr -dr com.apple.quarantine "/Applications/NDXVO Media Converter.app"
```

After that it opens normally, including after updates.

To remove this step entirely you need an Apple Developer ID ($99/year) and a
notarisation step in the workflow. The workflow is structured so that adding it
later is a matter of supplying the certificate and credentials as repository
secrets — no restructuring required.

---

## Claude in GitHub

`.github/workflows/claude.yml` lets you mention `@claude` in an issue or pull
request and have it do the work. It responds to a mention in an issue comment, a
PR review comment, a PR review body, and in the title or body of a newly opened
issue.

It needs two things that are not in this repository:

1. The [Claude GitHub App](https://github.com/apps/claude) installed here
2. A repository secret with the credential — `CLAUDE_CODE_OAUTH_TOKEN` for a
   Claude subscription (generate it with `claude setup-token`), or
   `ANTHROPIC_API_KEY` for API billing

Running `/install-github-app` inside Claude Code sets up both and opens a pull
request with the workflow; the checked-in file is the manual equivalent.

Only users with write access to the repository can trigger it, and bot accounts
are rejected, so a bot cannot put Claude into a loop.

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
