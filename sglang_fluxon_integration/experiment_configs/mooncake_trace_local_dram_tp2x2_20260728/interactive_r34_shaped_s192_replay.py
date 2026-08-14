#!/usr/bin/env python3
"""Replay the frozen nested Interactive-derived S192xT24 workload."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "interactive_r34_shaped_replay.py"
spec = importlib.util.spec_from_file_location(
    "interactive_r34_shaped_s192_base", BASE_PATH
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import base shaped replayer: {BASE_PATH}")
_base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = _base
spec.loader.exec_module(_base)

# Keep the existing S96 ranking identity so the first 96 sessions are byte-for-
# byte the frozen S96 cohort, then append ranks 97-192.  The shared-prefix asset
# is also intentionally reused; only active-session working set changes.
_base.SCHEMA = "interactive_r34_shaped_s192t24_replay_v1"
_base.PROFILE = "interactive-r34-shaped-s192t24-shared-system-v1"
_base.SESSIONS = 192
_base.R34_TURN_PROMPT_TOTALS = tuple(
    value * 2 for value in _base.R34_TURN_PROMPT_TOTALS
)
_base.SELECTED_USERS_SHA256 = (
    "be10b68ec0593d6908cbbdd8a21c2c94da4e9a56dc2d26da3a26debfd90c4cd3"
)
_base.SELECTION_COORDINATES_SHA256 = (
    "a3708c13c86111dc0499ea024a2428d221b2e66fcab376fc7fd793c330209660"
)
_base.SHAPED_RECORDS_SHA256 = (
    "b6805506eae7576bbff23ce9cde4012289037cef610caeec5ace7130d92ef807"
)
_base.EXPECTED_UNIQUE_PAGES = 67_454
_base.EXPECTED_UNIQUE_EXACT_TOKENS = 4_310_590

# The delegated replay code records the executable profile wrapper, not the
# imported implementation file, as script_path/script_sha256 in run evidence.
_base.__file__ = str(Path(__file__).resolve())


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def main(argv: list[str] | None = None) -> int:
    return _base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
