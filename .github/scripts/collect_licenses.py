#!/usr/bin/env python3
"""Collect the third-party license texts that ship inside a build.

The bundled ffmpeg is GPL, so every binary has to carry its license text, a
note of exactly which build it is, and directions to its source code. This
script assembles all of that into one folder, which the build then embeds in
the app, copies into the .dmg and attaches to the GitHub Release:

    <out>/THIRD-PARTY-NOTICES.txt   rendered from licenses/THIRD-PARTY-NOTICES.template.txt
    <out>/ffmpeg/                   FFmpeg's own LICENSE.md and COPYING.* files,
                                    plus BUILD-INFO.txt ("ffmpeg -version" output)
    <out>/Pillow/LICENSE.txt        from the installed Pillow wheel
    <out>/Python/LICENSE.txt        from the running interpreter, if present

It fails the build when the bundled ffmpeg is not the release whose source the
Release attaches (FFMPEG_SOURCE_VERSION in build.yml), or when it was built
with --enable-nonfree and so may not be redistributed at all. Usage:

    python .github/scripts/collect_licenses.py --ffmpeg vendor/ffmpeg \\
        --platform "macOS arm64" --app-version 1.2.0 \\
        --ffmpeg-source-version 7.1 --imageio-ffmpeg-version 0.6.0 \\
        --release-url https://github.com/<owner>/<repo>/releases/tag/v1.2.0 \\
        --out vendor/licenses
"""

import argparse
import importlib.metadata
import io
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from string import Template

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LICENSES_DIR = os.path.join(ROOT, "licenses")
TEMPLATE = os.path.join(LICENSES_DIR, "THIRD-PARTY-NOTICES.template.txt")
FFMPEG_TEXTS = os.path.join(LICENSES_DIR, "ffmpeg")


def warn(message):
    # Shows up as an annotation on the run page; harmless locally.
    print("::warning::%s" % message)


def is_inside(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # different drives on Windows
        return False


def ffmpeg_info(ffmpeg, expected_version):
    out = subprocess.run([ffmpeg, "-version"], capture_output=True, check=True,
                         encoding="utf-8", errors="replace").stdout
    first = out.splitlines()[0] if out else ""
    m = re.match(r"ffmpeg version (\S+)", first)
    if m is None:
        sys.exit("error: unexpected 'ffmpeg -version' output: %r" % first)
    full_version = m.group(1)
    release = re.match(r"n?(\d+(?:\.\d+)+)", full_version)
    if release is None or release.group(1) != expected_version:
        sys.exit("error: bundled ffmpeg is %s, but the Release attaches the source of "
                 "FFmpeg %s. Update FFMPEG_SOURCE_VERSION / FFMPEG_SOURCE_SHA256 in "
                 "build.yml together with IMAGEIO_FFMPEG_VERSION."
                 % (full_version, expected_version))

    config = re.search(r"^configuration:(.*)$", out, re.M)
    flags = config.group(1).split() if config else []
    if "--enable-nonfree" in flags:
        sys.exit("error: this ffmpeg was built with --enable-nonfree and may not be "
                 "redistributed. Pick a different build.")
    gpl, v3 = "--enable-gpl" in flags, "--enable-version3" in flags
    if gpl and v3:
        license_name, license_file = "GNU GPL version 3 or later", "ffmpeg/COPYING.GPLv3"
    elif gpl:
        license_name, license_file = "GNU GPL version 2 or later", "ffmpeg/COPYING.GPLv2"
    elif v3:
        license_name, license_file = "GNU LGPL version 3 or later", "ffmpeg/COPYING.LGPLv3"
    else:
        license_name, license_file = "GNU LGPL version 2.1 or later", "ffmpeg/COPYING.LGPLv2.1"
    return out, full_version, license_name, license_file


def ffmpeg_origin(full_version, imageio_version):
    wheel = ("redistributed in the imageio-ffmpeg %s wheel "
             "(https://github.com/imageio/imageio-ffmpeg)" % imageio_version)
    if "gyan.dev" in full_version:
        return ('static "essentials" build from https://www.gyan.dev/ffmpeg/builds/,\n'
                "          %s" % wheel)
    return ("static build from https://github.com/imageio/imageio-binaries,\n"
            "          %s" % wheel)


def copy_pillow_license(out_dir):
    dist = importlib.metadata.distribution("pillow")
    found = [f for f in (dist.files or [])
             if os.path.basename(str(f)).upper().startswith("LICENSE")]
    if not found:
        sys.exit("error: no LICENSE file in the installed Pillow distribution")
    target = os.path.join(out_dir, "Pillow")
    os.makedirs(target)
    shutil.copyfile(str(found[0].locate()), os.path.join(target, "LICENSE.txt"))
    license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    return dist.version, (license_name or "MIT-CMU").strip()


def copy_python_license(out_dir):
    candidates = [
        os.path.join(sys.base_prefix, "LICENSE.txt"),
        os.path.join(sysconfig.get_path("stdlib"), "LICENSE.txt"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            target = os.path.join(out_dir, "Python")
            os.makedirs(target)
            shutil.copyfile(path, os.path.join(target, "LICENSE.txt"))
            return "Python/LICENSE.txt"
    warn("Python's LICENSE.txt was not found; the notices link to it instead")
    return "https://docs.python.org/3/license.html"


def tcl_version():
    try:
        import tkinter
        return tkinter.Tcl().eval("info patchlevel")
    except Exception as exc:
        warn("could not read the Tcl/Tk version: %s" % exc)
        return "(version unknown)"


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        warn("%s is not installed; its version is left out of the notices" % name)
        return "(version unknown)"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ffmpeg", required=True, help="the ffmpeg binary being bundled")
    parser.add_argument("--platform", required=True, help='e.g. "Windows x64"')
    parser.add_argument("--app-version", required=True)
    parser.add_argument("--ffmpeg-source-version", required=True,
                        help="FFmpeg release whose source the Release attaches")
    parser.add_argument("--imageio-ffmpeg-version", required=True)
    parser.add_argument("--release-url", required=True,
                        help="GitHub Release page the build is published on")
    parser.add_argument("--out", required=True, help="output folder (recreated)")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out)
    if is_inside(out_dir, LICENSES_DIR):
        sys.exit("error: --out must not be inside %s" % LICENSES_DIR)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    build_info, full_version, license_name, license_file = ffmpeg_info(
        args.ffmpeg, args.ffmpeg_source_version)
    shutil.copytree(FFMPEG_TEXTS, os.path.join(out_dir, "ffmpeg"))
    with io.open(os.path.join(out_dir, "ffmpeg", "BUILD-INFO.txt"), "w", encoding="utf-8") as fh:
        fh.write(build_info)

    pillow_version, pillow_license = copy_pillow_license(out_dir)

    with io.open(TEMPLATE, encoding="utf-8") as fh:
        template = Template(fh.read())
    notices = template.substitute(
        app_version=args.app_version,
        platform=args.platform,
        ffmpeg_version=full_version,
        ffmpeg_license=license_name,
        ffmpeg_license_file=license_file,
        ffmpeg_origin=ffmpeg_origin(full_version, args.imageio_ffmpeg_version),
        ffmpeg_source_version=args.ffmpeg_source_version,
        ffmpeg_tarball="ffmpeg-%s.tar.xz" % args.ffmpeg_source_version,
        release_url=args.release_url,
        pillow_version=pillow_version,
        pillow_license=pillow_license,
        python_version=sys.version.split()[0],
        python_license_file=copy_python_license(out_dir),
        tcl_version=tcl_version(),
        pyinstaller_version=package_version("pyinstaller"),
    )
    with io.open(os.path.join(out_dir, "THIRD-PARTY-NOTICES.txt"), "w", encoding="utf-8") as fh:
        fh.write(notices)

    print("Collected third-party licenses into %s:" % out_dir)
    for dirpath, _, filenames in os.walk(out_dir):
        for name in sorted(filenames):
            print("  " + os.path.relpath(os.path.join(dirpath, name), out_dir))
    print("ffmpeg %s -> %s" % (full_version, license_name))


if __name__ == "__main__":
    main()
