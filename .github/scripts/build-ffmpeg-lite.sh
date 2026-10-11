#!/usr/bin/env bash
# Build the minimal ("lite") ffmpeg bundled in the -lite release variant.
#
# FFmpeg is configured with --disable-everything, then only what the converter
# asks of it is switched back on: the common input formats, the filters
# build_vf can emit, the MJPEG and PNG encoders, and the AVI / image muxers.
# No external library is linked apart from zlib, so the result is LGPL 2.1+
# and about 9.5 MB on Windows, against 87.6 MB for the imageio-ffmpeg build.
# AV1 input is deliberately not covered (it needs libdav1d).
#
# usage: bash .github/scripts/build-ffmpeg-lite.sh <version> <sha256> <output>
#
# Runs on macOS (Xcode clang) and in an MSYS2 UCRT64 shell on Windows (gcc,
# nasm, make, zlib; MINGW64 works too). Work files go to build/ffmpeg-lite under the current
# directory. build.yml caches <output> under a key that hashes this file, so
# any edit here forces a rebuild.
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "usage: $0 <ffmpeg version> <source sha256> <output binary>" >&2
  exit 2
fi
VERSION="$1"
SHA256="$2"
OUT="$3"

WORK="$PWD/build/ffmpeg-lite"
SRC="$WORK/ffmpeg-$VERSION"
TARBALL="$WORK/ffmpeg-$VERSION.tar.xz"
mkdir -p "$WORK/tmp"
# configure writes its probes to $TMPDIR; on Windows the inherited value is a
# backslash path that the MSYS2 shell cannot use.
export TMPDIR="$WORK/tmp"

join() { local IFS=,; echo "$*"; }

# Containers behind VIDEO_EXTS / IMAGE_EXTS.  mpegps (.mpg) leaves stream types
# open and probes them with the raw demuxers, so those are listed too.
DEMUXERS=(mov avi matroska mpegps mpegts asf flv ogg
          image2 image_jpeg_pipe image_png_pipe image_bmp_pipe
          image_webp_pipe image_tiff_pipe gif
          mpegvideo m4v h264 hevc aac ac3 mp3)
VIDEO_DECODERS=(h264 hevc mpeg4 mpeg1video mpeg2video h263 flv msmpeg4v1
                msmpeg4v2 msmpeg4v3 wmv1 wmv2 wmv3 vc1 vp6 vp6f vp8 vp9
                theora prores mjpeg png bmp gif webp tiff rawvideo)
# Audio is never decoded (-an), but without a decoder `ffmpeg -i` keeps reading
# up to probesize to learn the sample format and logs a warning per stream.
AUDIO_DECODERS=(aac mp3float mp2float ac3 eac3 opus vorbis flac alac wmav2
                pcm_s16le pcm_s16be pcm_s24le pcm_f32le)
PARSERS=(h264 hevc mpeg4video mpegvideo h263 vc1 vp8 vp9 mjpeg png bmp gif
         webp aac aac_latm mpegaudio ac3 opus vorbis flac)
# mjpeg: the export and the device preview.  png: the original preview pane.
ENCODERS=(mjpeg png)
MUXERS=(avi image2 image2pipe null)
# build_vf's chain plus what ffmpeg inserts itself (format, trim, rotate for
# autorotation); showinfo only helps when debugging a chain by hand.
FILTERS=(scale crop pad unsharp transpose hflip vflip fps format null trim
         rotate showinfo)

case "$(uname -s)" in
  Darwin)
    # --disable-autodetect also drops threading, so it is named explicitly.
    PLATFORM_FLAGS=(--cc=clang --enable-pthreads
                    --extra-cflags=-mmacosx-version-min=11.0
                    --extra-ldflags=-mmacosx-version-min=11.0)
    JOBS="$(sysctl -n hw.ncpu)"
    ;;
  UCRT64*|MINGW64*)
    # uname reports the MSYS2 environment (UCRT64_NT-..., MINGW64_NT-...); the
    # plain MSYS shell is not a target, since it links against msys-2.0.dll.
    # -static keeps libgcc, winpthreads and zlib inside the exe.  The only DLLs
    # left are Windows' own, the Universal C Runtime included (built into
    # Windows 10 and later, and needed by the bundled Python anyway).
    # Do not add --disable-x86asm:
    # with inline asm still on, swscale's YUV output came out garbled (7.1.5,
    # gcc 15).  Without nasm, configure stops, which is the right outcome.
    PLATFORM_FLAGS=(--enable-w32threads --extra-ldflags=-static)
    JOBS="$(nproc)"
    ;;
  *)
    echo "unsupported build host: $(uname -s)" >&2
    exit 1
    ;;
esac

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

if [ ! -f "$TARBALL" ]; then
  curl -fsSL --retry 3 -o "$TARBALL" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
fi
GOT="$(sha256_of "$TARBALL")"
if [ "$GOT" != "$SHA256" ]; then
  echo "::error::ffmpeg-$VERSION.tar.xz has SHA-256 $GOT, expected $SHA256"
  exit 1
fi

rm -rf "$SRC"
tar -xJf "$TARBALL" -C "$WORK"
cd "$SRC"

./configure \
  --extra-version=ndxvo-lite \
  --disable-everything --disable-autodetect --disable-network \
  --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
  --disable-avdevice --disable-postproc \
  --enable-zlib \
  --enable-protocol=file,pipe \
  --enable-demuxer="$(join "${DEMUXERS[@]}")" \
  --enable-decoder="$(join "${VIDEO_DECODERS[@]}" "${AUDIO_DECODERS[@]}")" \
  --enable-parser="$(join "${PARSERS[@]}")" \
  --enable-encoder="$(join "${ENCODERS[@]}")" \
  --enable-muxer="$(join "${MUXERS[@]}")" \
  --enable-filter="$(join "${FILTERS[@]}")" \
  "${PLATFORM_FLAGS[@]}"

make -j"$JOBS"
cd - >/dev/null

EXE="$SRC/ffmpeg"
[ -f "$EXE.exe" ] && EXE="$EXE.exe"
mkdir -p "$(dirname "$OUT")"
cp "$EXE" "$OUT"
if [ "$(uname -s)" = Darwin ]; then
  # Apple Silicon refuses to run an unsigned binary.  The app bundle is
  # re-signed later anyway; this lets the binary run on its own first.
  codesign --force --sign - "$OUT"
fi

"$OUT" -hide_banner -version | head -n 1
echo "Built $OUT: $(wc -c < "$OUT" | tr -d ' ') bytes"
