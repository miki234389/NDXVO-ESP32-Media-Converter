---
name: ndxvo-docs-drift
description: Use when checking whether README.md (and code comments) still match the NDXVO converter code and CI - before a release, after changing defaults, constants, GUI controls or the build workflow, or when asked "is the documentation up to date".
---

# Docs drift (README vs code vs CI)

Compare every concrete claim in README.md with its source of truth. Read the
README in full (it is short); pull code with
`python .claude/skills/ndxvo-project-map/scripts/outline.py --show <name>` or `--constants`.

## Claims to check

| README claim | Source of truth |
|---|---|
| Title `# NDXVO Media Converter` | `APP_TITLE`; build.yml `APP_NAME`; the `.app` name in the `xattr` line |
| Reference command | Module docstring at the top of `ndxvo_converter.py` |
| "Default settings emit a byte-for-byte identical file" | `Params.__init__` + `PIX_FMT` + `qscale_for(QUALITY_DEFAULT)`. Holds only with chroma `yuvj420p`, `-q:v 2`, rotation 180, fps 30, fit crop, sharpen 0 |
| Feature list | Controls built in `App._build_controls`: Fit mode, Crop X/Y, Centre crop, Rotation, Mirror H/V, Format (AVI / JPG), FPS, Quality, Sharpen, Pad colour, Video duration, Reset to defaults |
| "FPS (30 / 25)", "Python 3.9+", "Pillow" | `FPS_CHOICES`, module docstring, third-party imports |
| ffmpeg lookup order | `find_ffmpeg` |
| Build section: runners, artifact names, `archive: false`, retention, job layout | `.github/workflows/build.yml` |
| Mockup constants code block | `MOCKUP_SCREEN`, `MOCKUP_CROP`, `CORNER_RADIUS_RATIO` |
| Every file path mentioned | Exists in the repo |
| Filter-chain explanation | `build_vf` / `scaled_size` (see ndxvo-filter-chain) |

## Known drift found on 2026-10-11 (re-verify; may be fixed since)

- **`MOCKUP_SCREEN`**: the README says `(297, 227, 207, 385)`; the code says `(294, ...)`.
- **Undocumented settings.** Sharpen, the 1-10
  Quality dial (vs ffmpeg `-q:v`), and the frame-budget check and warning after
  Generate are not described in the README.
- **`archive: false`.** The README says artifacts upload with `archive: false`,
  but neither `upload-artifact` step in build.yml sets it. Either add it, or
  correct the README (downloads would then be zipped).

## Intentional differences (do not flag)

- **App title.** The original project brief named the app "NDXVO ESP32 File
  Converter". It was renamed to "NDXVO Media Converter" in commit 509fc7d.
- **Version shown.** `APP_VERSION` reads `1.0.0-dev` in source by design; CI stamps the real version.

## Output

Report a table: claim | README says | code/CI says | verdict (OK / DRIFT /
UNDOCUMENTED). Then propose concrete README edits in English. Edit README only
when the user asks. When the code is what looks wrong (not the README), say so
instead of "fixing" the docs to match a bug.
