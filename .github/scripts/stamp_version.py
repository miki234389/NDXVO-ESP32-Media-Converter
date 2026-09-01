#!/usr/bin/env python3
"""Write the build version into the application source.

The app keeps its version in a single line of the form:

    APP_VERSION = "1.0.0-dev"

This script replaces that line's value and verifies the result, so a build can
never silently ship the placeholder version. Usage:

    python .github/scripts/stamp_version.py 1.2.0
"""

import io
import os
import re
import sys

PATTERN = re.compile(r'^APP_VERSION = "[^"]*"$', re.M)


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: stamp_version.py <version>")
    version = argv[1].strip()
    if not version:
        sys.exit("error: empty version")
    if '"' in version or "\\" in version:
        sys.exit("error: version must not contain quotes or backslashes")

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    target = os.path.join(root, "ndxvo_converter.py")

    with io.open(target, encoding="utf-8") as fh:
        source = fh.read()

    replacement = 'APP_VERSION = "%s"' % version
    stamped, count = PATTERN.subn(replacement, source, count=1)
    if count != 1:
        sys.exit("error: could not find an 'APP_VERSION = \"...\"' line in %s" % target)

    with io.open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(stamped)

    # Read it back rather than trusting the write.
    with io.open(target, encoding="utf-8") as fh:
        found = PATTERN.search(fh.read())
    if found is None or found.group(0) != replacement:
        sys.exit("error: verification failed after writing %s" % target)

    print("Stamped %s -> %s" % (os.path.basename(target), replacement))


if __name__ == "__main__":
    main(sys.argv)
