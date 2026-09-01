#!/usr/bin/env bash
#
# Decide which version this build carries and validate it.
#
#   - manual run  -> the "version" input from the workflow form
#   - tag push    -> the tag name with any leading "v" removed
#
# Writes  version=<value>  to $GITHUB_OUTPUT.
set -euo pipefail

if [ -n "${INPUT_VERSION:-}" ]; then
  VERSION="${INPUT_VERSION}"
  SOURCE="workflow input"
else
  VERSION="${GITHUB_REF_NAME:-}"
  SOURCE="git tag ${VERSION:-<none>}"
  VERSION="${VERSION#v}"
fi

# Strip stray whitespace a copy-paste into the form may have carried in.
VERSION="$(printf '%s' "${VERSION}" | tr -d '[:space:]')"

if [ -z "${VERSION}" ]; then
  echo "::error::No version available. Run the workflow manually and fill in the version field, or push a tag like v1.0.0."
  exit 1
fi

# MAJOR.MINOR.PATCH with an optional pre-release suffix.
if ! printf '%s' "${VERSION}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.]*)?$'; then
  echo "::error::Invalid version '${VERSION}' (from ${SOURCE}). Expected MAJOR.MINOR.PATCH with an optional pre-release suffix — for example 1.0.0, 2.1.3, 1.4.0-rc1 or 1.4.0-beta.2 — and no leading 'v'."
  exit 1
fi

echo "Building version ${VERSION} (from ${SOURCE})"
echo "version=${VERSION}" >> "${GITHUB_OUTPUT}"
