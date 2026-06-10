"""Configuration & discovery helpers.

Everything is overridable via environment variables so the same package works on
any Windows box without code edits:

  HWINFO_EXE          full path to HWiNFO64.exe (otherwise we search common dirs)
  HWINFO_REPORT_DIR   folder of manually-saved HWiNFO reports, used as a fallback
                      when CLI report generation is unavailable (e.g. free edition)
  HWINFO_REPORT_TIMEOUT  seconds to wait for a generated report file (default 45)
"""

from __future__ import annotations

import os
import shutil

# Common install locations for HWiNFO64.exe on Windows.
_DEFAULT_EXE_PATHS = [
    r"C:\Program Files\HWiNFO64\HWiNFO64.exe",
    r"C:\Program Files (x86)\HWiNFO64\HWiNFO64.exe",
    r"C:\Program Files\HWiNFO\HWiNFO64.exe",
    r"C:\Program Files (x86)\HWiNFO\HWiNFO64.exe",
]


def find_hwinfo_exe() -> str | None:
    """Locate HWiNFO64.exe: env override -> common paths -> PATH."""
    env = os.environ.get("HWINFO_EXE")
    if env:
        return env if os.path.isfile(env) else None
    for path in _DEFAULT_EXE_PATHS:
        if os.path.isfile(path):
            return path
    found = shutil.which("HWiNFO64") or shutil.which("HWiNFO64.exe")
    return found


def report_fallback_dir() -> str | None:
    d = os.environ.get("HWINFO_REPORT_DIR")
    if d and os.path.isdir(d):
        return d
    return None


def report_timeout() -> float:
    try:
        return float(os.environ.get("HWINFO_REPORT_TIMEOUT", "45"))
    except ValueError:
        return 45.0
