#!/usr/bin/env python3
"""Require handoff updates for code changes; operational changes also require README review."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPERATIONAL = {
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
}


def validate_changed_files(paths):
    paths = set(paths)
    errors = []
    meaningful = any(
        p.startswith(("apps/", "config/", "templates/", "static/", "frontend/", "docker/", "scripts/", ".github/"))
        or p in OPERATIONAL
        for p in paths
    )
    operational = any(p in OPERATIONAL or p.startswith(("docker/", "config/settings/", "scripts/")) for p in paths)
    if meaningful and "project.md" not in paths:
        errors.append("Update project.md with actual changes, verification, and remaining work.")
    if operational and "README.md" not in paths:
        errors.append("Review and update README.md for operational changes.")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Git revision to compare with HEAD")
    parser.add_argument("--files", nargs="*", help="Explicit changed paths for local checks")
    args = parser.parse_args()
    for name in ("README.md", "project.md", "AGENTS.md"):
        if not (ROOT / name).is_file():
            raise SystemExit(f"Missing required documentation: {name}")
    if args.files is not None:
        paths = args.files
    elif args.base:
        result = subprocess.run(  # noqa: S603 - fixed command, no shell
            ["git", "diff", "--name-only", args.base, "HEAD"],  # noqa: S607 - trusted git on PATH
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )  # noqa: S603,S607 - fixed executable, revision passed as argument
        paths = result.stdout.splitlines()
    else:
        raise SystemExit("Supply --base <revision> or --files <changed paths>; no baseline is inferred.")
    errors = validate_changed_files(paths)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation guard passed. Content accuracy still requires review.")


if __name__ == "__main__":
    main()
