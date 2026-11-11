#!/usr/bin/env python3
"""Resolve the active mind's name and brain directory.

The shell runners export ``PROJECT_NAME`` and ``BRAIN_DIR`` before starting
Python scripts, so a script usually needs nothing from the caller. When a
script is run directly, either variable can be supplied:

    BRAIN_DIR=/path/to/nova-brain python3 runner/scripts/deliver-reading.py
    PROJECT_NAME=nova python3 runner/scripts/deliver-reading.py

No mind name is baked in here: the name always comes from the environment, the
brain directory, or the caller.
"""

from __future__ import annotations

import os
from pathlib import Path

# Used only when nothing identifies the mind; keeps scripts from crashing.
_FALLBACK_NAME = "mind"


def _from_config() -> str:
    """Read PROJECT_NAME from the runner config when the environment is bare."""
    runner_dir = Path(__file__).resolve().parent.parent
    for filename in ("config.local.env", "config.env"):
        path = runner_dir / filename
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() != "PROJECT_NAME":
                continue
            name = value.strip().strip('"').strip("'")
            if name:
                return name
    return ""


def project_name() -> str:
    """Return the lowercase mind name (e.g. ``nova``)."""
    name = (os.environ.get("PROJECT_NAME") or "").strip()
    if name:
        return name

    brain = (os.environ.get("BRAIN_DIR") or "").strip()
    if brain:
        base = Path(brain).expanduser().name
        if base.endswith("-brain"):
            base = base[: -len("-brain")]
        if base:
            return base

    configured = _from_config()
    if configured:
        return configured

    return _FALLBACK_NAME


def display_name() -> str:
    """Return the mind name with its first letter capitalised (e.g. ``Nova``)."""
    name = project_name()
    return name[:1].upper() + name[1:]


def guide_file() -> str:
    """Return the session guide filename (e.g. ``NOVA.md``)."""
    return project_name().upper() + ".md"


def brain_dir() -> Path:
    """Return the brain directory, preferring ``BRAIN_DIR``."""
    configured = (os.environ.get("BRAIN_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = Path(__file__).resolve().parent.parent.parent
    return root / f"{project_name()}-brain"
