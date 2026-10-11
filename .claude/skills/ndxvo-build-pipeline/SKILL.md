---
name: ndxvo-build-pipeline
description: Use for anything about building and releasing the NDXVO converter - GitHub Actions build.yml, version resolution and stamping, macOS .dmg / Windows .exe packaging with PyInstaller, bundled ffmpeg, Gatekeeper/quarantine on Mac, inspecting failed runs, or the @claude workflow.
---

# Build and release pipeline

## Three ways a build runs (`.github/workflows/build.yml`)

| Mode | Trigger | Result |
|---|---|---|
| Test build | Actions -> Build -> Run workflow, `release` unticked | Artifacts only (90 days, login needed) |
| Release from the button | same form, `release` ticked | Tags `v<version>` on the built commit and publishes a GitHub Release |
| Release from a tag | `git push origin v1.2.0` | Same as above, version taken from the tag |

## Job graph and version flow

    preflight --+-- macos ---+
                +-- windows -+-- release   (only if preflight.release == 'true')

1. **preflight**: `resolve-version.sh` takes the form input or the tag name
   (strips the leading `v`, trims whitespace). It validates against
   `^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.]*)?$` and writes `version=`.
   For a manual release it also checks the tag is still free, so the run fails
   in seconds rather than after a full build.
2. **Each build job**: `stamp_version.py <v>` rewrites the single
   `APP_VERSION = "..."` line and reads it back. If the line is missing or
   reformatted, the build fails. That version appears in the title bar, the
   artifact names and (on macOS) Info.plist.
3. **release**: runs only after both builds succeed. It pushes the tag with
   `GITHUB_TOKEN`, which deliberately does not start another workflow run, so
   there is no duplicate build. It then publishes with
   `softprops/action-gh-release`.

## Per platform

**macOS**:
- Runs on `macos-14` (arm64 only; Intel Macs are not covered).
- Builds with `pyinstaller --windowed --onedir --add-binary "vendor/ffmpeg:." --hidden-import PIL._tkinter_finder`.
- Info.plist versions are set **before** `codesign --force --deep --sign -`, because editing the bundle after signing breaks the signature.
- Packages a `.dmg` with `hdiutil`.
- A verify step mounts the `.dmg` and runs `Contents/Frameworks/ffmpeg -version`.

**Windows**:
- Runs on `windows-latest`, with `--onefile --add-binary "vendor/ffmpeg.exe;."`. The separator is `;` on Windows and `:` on macOS.
- A verify step lists the PyInstaller archive and requires `ffmpeg.exe` in it.

**ffmpeg** comes from the `imageio-ffmpeg` wheel, pinned by `IMAGEIO_FFMPEG_VERSION`.
The same pin is duplicated in `tools/verify-ffmpeg-embedded.ps1`; keep them in sync.

At runtime, `find_ffmpeg` searches `sys._MEIPASS` (the onefile temp dir, or
`Contents/Frameworks` in a PyInstaller 6 `.app`), then the exe dir and
`Contents/Resources`, then PATH and Homebrew. Pull it with
`outline.py --show find_ffmpeg`.

## Mac first launch

The app is ad-hoc signed but **not notarised**, so Gatekeeper reports it as
"damaged". Fix it once with:

    xattr -dr com.apple.quarantine "/Applications/NDXVO Media Converter.app"

Removing that step needs an Apple Developer ID ($99/yr) plus a notarisation
step using secrets.

## Risks to keep in mind

- `pyinstaller` and `pillow` are installed **unpinned**, so builds are not
  reproducible. A PyInstaller layout change would break the `Contents/Frameworks/ffmpeg`
  verify path and possibly `find_ffmpeg`. Pin them if a build suddenly breaks.
- `APP_NAME` in build.yml has to match `APP_TITLE` in the code, and the `.app`
  name used in the README's `xattr` line.
- Action versions (`checkout@v6`, `setup-python@v6`, `upload/download-artifact@v7`,
  `action-gh-release@v3`): look up current majors on the web before claiming
  they are outdated.

## Local checks (safe)

- **Version validation**: `INPUT_VERSION=1.4.0-rc1 GITHUB_OUTPUT=/dev/stdout bash .github/scripts/resolve-version.sh`
  needs Git Bash on Windows. Try good values (`1.0.0`, `2.1.3`, `1.4.0-beta.2`)
  and bad ones (`v1.0.0`, `1.0`, `1.0.0.0`).
- **Stamping**: `stamp_version.py` **modifies `ndxvo_converter.py` in place**.
  Run it on a copy, or restore with `git checkout -- ndxvo_converter.py` afterwards.
- **Windows packaging proof**: `powershell -ExecutionPolicy Bypass -File tools\verify-ffmpeg-embedded.ps1`.
  This is slow: it runs two PyInstaller builds.

## Inspecting CI with gh (read-only)

    gh run list --workflow build.yml --limit 5
    gh run view <run-id> --log-failed
    gh run download <run-id>            # fetch the .dmg / .exe
    gh release list --limit 5

**Trigger** builds only when the user explicitly asks.
- A test build: `gh workflow run build.yml -f version=1.2.0 -f release=false`.
- `release=true`, or pushing a `v*` tag, creates a public tag and Release. Confirm the version with the user first.

## @claude workflow (`claude.yml`)

It responds to `@claude` in issue comments, PR review comments, review bodies,
and new or assigned issues. It is limited to users with write access, and bots
are rejected. It needs the Claude GitHub App and a `CLAUDE_CODE_OAUTH_TOKEN`
(or `ANTHROPIC_API_KEY`) secret. Runs are cancelled and replaced per issue.
