"""HWiNFO MCP server.

Runs on the Windows PC where HWiNFO is installed and exposes its data to Claude
over stdio. Register it with, e.g.:

    claude mcp add hwinfo -- hwinfo-mcp
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import config, report
from .shared_memory import read_sensors

mcp = FastMCP("hwinfo")

# Memory-related substrings for the live-sensor convenience tool.
_MEMORY_SENSOR_HINTS = ("memory", "dram", "ram ", "vddq", "vdd2", "vpp")


@mcp.tool()
def get_memory_timings() -> dict:
    """Get current RAM timings (tCAS/tCL, tRCD, tRP, tRAS, tRC, Command Rate,
    memory speed/clock) and SPD info, parsed from a HWiNFO report.

    Requires HWiNFO64 (Pro for automatic CLI reports; on the free edition save a
    report via the GUI into HWINFO_REPORT_DIR as a fallback).
    """
    try:
        data, source = report.load_report_json()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    result = report.extract_memory_timings(data)
    result["ok"] = True
    result["source"] = source
    return result


@mcp.tool()
def get_hardware_report(section: str | None = None) -> dict:
    """Get the full HWiNFO hardware/config report (CPU, motherboard, memory,
    GPU, drives, ...).

    If `section` is given (case-insensitive substring, e.g. "memory", "cpu",
    "drive"), only matching subtrees of the report are returned; otherwise the
    whole report is returned.
    """
    try:
        data, source = report.load_report_json()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}

    if section:
        subtrees = [
            {"path": " / ".join(p), "data": sub}
            for p, sub in report._find_subtrees(data, (section.lower(),))
        ]
        return {"ok": True, "source": source, "section": section, "matches": subtrees}
    return {"ok": True, "source": source, "report": data}


@mcp.tool()
def get_live_sensors(filter: str | None = None) -> dict:
    """Get live HWiNFO sensor readings (temperatures, clocks, voltages, fans,
    usage, power) from the Shared Memory interface.

    `filter` is an optional case-insensitive substring matched against the
    sensor group name or reading label (e.g. "cpu", "gpu", "fan", "memory").

    Requires HWiNFO running with 'Shared Memory Support' enabled. On the free
    edition shared memory stops after ~12h and needs HWiNFO restarted.
    """
    return read_sensors(name_filter=filter)


@mcp.tool()
def get_memory_sensors() -> dict:
    """Convenience: live sensor readings related to memory (memory clock,
    DRAM/VDDQ voltages, memory usage, etc.) from Shared Memory."""
    out = read_sensors()
    if not out.get("ok"):
        return out
    readings = [
        r for r in out["readings"]
        if any(h in r["sensor"].lower() or h in r["label"].lower()
               for h in _MEMORY_SENSOR_HINTS)
    ]
    out["readings"] = readings
    out["num_readings"] = len(readings)
    return out


@mcp.tool()
def get_raw_report(fmt: str = "text") -> dict:
    """Return the raw HWiNFO report content for inspection/debugging the schema.

    `fmt` is one of: "json", "text", "csv", "xml". Useful to discover the exact
    keys HWiNFO uses on this machine so memory-timing parsing can be tuned.
    """
    try:
        content, source = report.generate_report_text(fmt)
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    truncated = len(content) > 200_000
    return {
        "ok": True,
        "source": source,
        "format": fmt,
        "truncated": truncated,
        "content": content[:200_000],
    }


@mcp.tool()
def hwinfo_status() -> dict:
    """Diagnostics: report what the server can see (HWiNFO exe, fallback dir,
    and whether shared memory is currently readable)."""
    sensors = read_sensors()
    return {
        "ok": True,
        "hwinfo_exe": config.find_hwinfo_exe(),
        "report_fallback_dir": config.report_fallback_dir(),
        "report_timeout_s": config.report_timeout(),
        "shared_memory_readable": bool(sensors.get("ok")),
        "shared_memory_error": None if sensors.get("ok") else sensors.get("error"),
        "live_reading_count": sensors.get("num_readings", 0),
    }


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
