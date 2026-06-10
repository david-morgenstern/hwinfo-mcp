"""Generate and parse HWiNFO hardware reports (static config: memory timings,
SPD, CPU, motherboard, drives, ...).

Live sensors come from shared_memory.py; *timings* are static config data and
only appear in HWiNFO's report output, so we generate a report and parse it.

Report generation strategy:
  1. Try the CLI:  HWiNFO64.exe -j<file>   (JSON; also -r text, -c csv, -x xml).
     This is the clean path on HWiNFO64 Pro.
  2. If the CLI produces nothing (the free edition may restrict report
     automation), fall back to the newest report file in HWINFO_REPORT_DIR that
     you saved manually from the HWiNFO GUI (File -> Save Report).

The JSON report's exact key names can vary across HWiNFO versions, so parsing is
deliberately schema-tolerant: we recursively search the tree for memory-related
nodes and timing-looking fields rather than assuming fixed paths. Use the
`get_raw_report` MCP tool to inspect the real structure and refine if needed.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
import time

from . import config

_FLAGS = {"json": "-j", "text": "-r", "csv": "-c", "xml": "-x"}
_EXTS = {"json": ".json", "text": ".txt", "csv": ".csv", "xml": ".xml"}

# Substrings (lower-case) used to spot the memory area of the report tree.
_MEMORY_KEYS = ("memory", "dram", "spd", "dimm")

# Substrings that identify an individual timing/speed field.
_TIMING_KEYS = (
    "tcas", "cas latency", "trcd", "ras to cas", "trp", "ras precharge",
    "tras", "trc", "trfc", "twr", "tfaw", "trrd", "command rate", "cr ",
    "cycle time", "bank cycle", "memory clock", "memory speed", "frequency",
    "timing", "tcl", "tcwl", "twtr", "trtp", "tcke", "tref",
)


def _newest_in_dir(directory: str, ext: str) -> str | None:
    matches = glob.glob(os.path.join(directory, f"*{ext}"))
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _wait_for_file(path: str, timeout: float) -> bool:
    """Wait until `path` exists and its size has stopped growing."""
    deadline = time.time() + timeout
    last_size = -1
    stable_for = 0.0
    while time.time() < deadline:
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > 0 and size == last_size:
                stable_for += 0.3
                if stable_for >= 0.9:  # size held steady for ~1s
                    return True
            else:
                stable_for = 0.0
            last_size = size
        time.sleep(0.3)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def generate_report_text(fmt: str = "json") -> tuple[str, str]:
    """Produce a report and return (content, source_description).

    Raises RuntimeError if neither CLI generation nor a fallback file works.
    """
    if fmt not in _FLAGS:
        raise ValueError(f"Unsupported report format {fmt!r}; use one of {list(_FLAGS)}.")

    ext = _EXTS[fmt]
    exe = config.find_hwinfo_exe()
    errors: list[str] = []

    # --- 1. CLI generation -------------------------------------------------
    if exe:
        out_path = os.path.join(
            tempfile.gettempdir(), f"hwinfo_mcp_report_{int(time.time())}{ext}"
        )
        # HWiNFO wants the filename glued to the flag, e.g. -jC:\path\report.json
        cmd = [exe, f"{_FLAGS[fmt]}{out_path}"]
        proc = None
        try:
            proc = subprocess.Popen(cmd)
            if _wait_for_file(out_path, config.report_timeout()):
                with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                return content, f"CLI: {' '.join(cmd)}"
            errors.append(
                "HWiNFO ran but produced no report file within the timeout "
                "(CLI report automation may require HWiNFO64 Pro)."
            )
        except OSError as exc:
            errors.append(f"Failed to launch HWiNFO: {exc}")
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
            try:
                if os.path.isfile(out_path):
                    os.remove(out_path)
            except OSError:
                pass
    else:
        errors.append(
            "HWiNFO64.exe not found (set HWINFO_EXE to its full path)."
        )

    # --- 2. Fallback: newest manually-saved report -------------------------
    fallback_dir = config.report_fallback_dir()
    if fallback_dir:
        newest = _newest_in_dir(fallback_dir, ext)
        if newest:
            with open(newest, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            return content, f"fallback file: {newest}"
        errors.append(
            f"No '*{ext}' report found in HWINFO_REPORT_DIR ({fallback_dir}). "
            f"Generate one via HWiNFO GUI: File -> Save Report."
        )
    else:
        errors.append(
            "No HWINFO_REPORT_DIR fallback configured."
        )

    raise RuntimeError(" | ".join(errors))


# --------------------------------------------------------------------------
# Schema-tolerant parsing helpers
# --------------------------------------------------------------------------

def _walk_leaves(obj, path=()):
    """Yield (path_tuple, key, value) for every scalar leaf in a nested
    dict/list structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from _walk_leaves(v, path + (str(k),))
            else:
                yield path, str(k), v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_leaves(v, path + (f"[{i}]",))


def _find_subtrees(obj, keywords, path=()):
    """Yield (path_tuple, subtree) for any dict key whose name contains one of
    `keywords` (case-insensitive)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(kw in kl for kw in keywords):
                yield path + (str(k),), v
            if isinstance(v, (dict, list)):
                yield from _find_subtrees(v, keywords, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _find_subtrees(v, keywords, path + (f"[{i}]",))


def extract_memory_timings(report_json) -> dict:
    """Best-effort extraction of RAM timings/speed from a parsed JSON report."""
    timings: list[dict] = []
    seen = set()

    for path, key, value in _walk_leaves(report_json):
        full = " / ".join(path + (key,)).lower()
        in_memory_area = any(mk in full for mk in _MEMORY_KEYS)
        looks_like_timing = any(tk in key.lower() for tk in _TIMING_KEYS)
        if in_memory_area and looks_like_timing:
            sig = (full, str(value))
            if sig in seen:
                continue
            seen.add(sig)
            timings.append({
                "path": " / ".join(path),
                "field": key,
                "value": value,
            })

    # Also surface the raw memory subtree(s) so nothing is lost if the
    # field-name heuristics miss a vendor-specific label.
    memory_sections = [
        {"path": " / ".join(p), "data": sub}
        for p, sub in _find_subtrees(report_json, _MEMORY_KEYS)
    ]

    return {
        "timings": timings,
        "memory_sections": memory_sections,
        "note": (
            "Parsing is schema-tolerant/best-effort. If 'timings' looks "
            "incomplete, call get_raw_report to inspect the real JSON keys."
        ),
    }


def load_report_json():
    """Generate a JSON report and return (parsed_obj, source_description)."""
    content, source = generate_report_text("json")
    try:
        return json.loads(content), source
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Report from {source} is not valid JSON ({exc}). "
            f"Try get_raw_report(fmt='text') to inspect it."
        ) from exc
