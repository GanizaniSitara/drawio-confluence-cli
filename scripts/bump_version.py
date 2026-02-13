#!/usr/bin/env python
"""Bump version in __init__.py"""

import re
import sys
from pathlib import Path


def get_current_version():
    init_file = Path(__file__).parent.parent / "src" / "drawio_cli" / "__init__.py"
    content = init_file.read_text()
    match = re.search(r'__version__ = ["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)
    raise ValueError("Could not find __version__ in __init__.py")


def bump_version(version_type):
    init_file = Path(__file__).parent.parent / "src" / "drawio_cli" / "__init__.py"
    content = init_file.read_text()

    match = re.search(r'__version__ = ["\']([^"\']+)["\']', content)
    if not match:
        raise ValueError("Could not find __version__ in __init__.py")

    current = match.group(1)
    parts = [int(p) for p in current.split(".")]

    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {current}")

    major, minor, patch = parts

    if version_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif version_type == "minor":
        minor += 1
        patch = 0
    elif version_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid version type: {version_type}")

    new_version = f"{major}.{minor}.{patch}"

    # Update file
    new_content = re.sub(
        r'__version__ = ["\'][^"\']+["\']',
        f'__version__ = "{new_version}"',
        content
    )
    init_file.write_text(new_content)

    print(f"Version bumped: {current} → {new_version}")
    return new_version


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python bump_version.py [major|minor|patch]")
        print(f"Current version: {get_current_version()}")
        sys.exit(1)

    version_type = sys.argv[1]
    bump_version(version_type)
