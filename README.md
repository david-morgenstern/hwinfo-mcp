# hwinfo-mcp

An MCP server that exposes **HWiNFO** data on a **Windows PC** to Claude:

- **Memory timings + SPD** (tCAS/tCL, tRCD, tRP, tRAS, tRC, Command Rate, speed) — like the values HWiNFO64 shows in its memory report.
- **Full hardware report** (CPU, motherboard, memory, GPU, drives), queryable by section.
- **Live sensors** (temperatures, clocks, voltages, fans, usage, power) via HWiNFO's Shared Memory interface.

It runs **on the Windows machine** (where HWiNFO and the hardware live) and talks to Claude over stdio. Built it on a Mac — copy this folder to the Windows PC to use it.

---

## How it works

| Data | Source |
|------|--------|
| Live sensors | HWiNFO **Shared Memory v2** (`Global\HWiNFO_SENS_SM2`), opened read-only through the Win32 mapping API via Python's stdlib `ctypes` |
| Memory timings / full report | HWiNFO **report file**: tries `HWiNFO64.exe -j<file>` (JSON), falls back to a manually-saved report |

Memory timings are *static config* data, so they only appear in HWiNFO **reports**, not in the live shared-memory sensor stream — hence the two paths.

## Free-edition caveats ⚠️

You said the edition is free / unknown. Two things to know:

1. **CLI report automation may be Pro-only.** If `get_memory_timings` / `get_hardware_report` report that no file was produced, use the GUI fallback: in HWiNFO do **File → Save Report** (pick **JSON**) into a folder, then set `HWINFO_REPORT_DIR` to that folder. The server will parse the newest report there.
2. **Shared Memory on the free edition stops after ~12 hours** and needs HWiNFO restarted. Enable it under **HWiNFO → Settings → Main Settings → "Shared Memory Support"**, and keep HWiNFO running.

## Tools exposed

- `get_memory_timings()` — RAM timings + SPD from the report.
- `get_hardware_report(section?)` — full report, or just subtrees matching `section` (e.g. `"memory"`, `"cpu"`).
- `get_live_sensors(filter?)` — all live readings, optionally filtered (e.g. `"gpu"`, `"fan"`).
- `get_memory_sensors()` — live readings related to memory.
- `get_raw_report(fmt?)` — raw report text (`json`/`text`/`csv`/`xml`) to inspect the real schema.
- `hwinfo_status()` — diagnostics (exe found? shared memory readable? reading count).

---

## Install on the Windows PC

Repo: <https://github.com/david-morgenstern/hwinfo-mcp> · prebuilt assets on the [Releases page](https://github.com/david-morgenstern/hwinfo-mcp/releases/latest).

### A. pip straight from GitHub (needs Python 3.10+) — simplest
```powershell
pip install "git+https://github.com/david-morgenstern/hwinfo-mcp"
```
Installs a `hwinfo-mcp` command.

### B. Standalone .exe — no Python needed
Download `hwinfo-mcp.exe` from the [latest release](https://github.com/david-morgenstern/hwinfo-mcp/releases/latest) and put it anywhere, e.g. `C:\Tools\hwinfo-mcp.exe`.

### C. pip from a downloaded wheel
Download `hwinfo_mcp-*.whl` from the release, then:
```powershell
pip install hwinfo_mcp-0.1.0-py3-none-any.whl
```

### D. From a local checkout
```powershell
cd hwinfo-mcp
pip install .        # or: pipx install .
```

> The release `.exe` is produced by the `release` GitHub Actions workflow (it also builds the wheel/sdist). Cut a new release by pushing a tag: `git tag v0.1.1 && git push origin v0.1.1`.

## Register with Claude Code

```powershell
:: if installed via pip/pipx:
claude mcp add hwinfo -- hwinfo-mcp

:: if using the standalone exe:
claude mcp add hwinfo -- "C:\path\to\dist\hwinfo-mcp.exe"
```

With environment overrides (example):
```powershell
claude mcp add hwinfo ^
  -e HWINFO_EXE="C:\Program Files\HWiNFO64\HWiNFO64.exe" ^
  -e HWINFO_REPORT_DIR="C:\Users\you\Documents\hwinfo-reports" ^
  -- hwinfo-mcp
```

For **Claude Desktop**, add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "hwinfo": {
      "command": "hwinfo-mcp",
      "env": {
        "HWINFO_EXE": "C:\\Program Files\\HWiNFO64\\HWiNFO64.exe",
        "HWINFO_REPORT_DIR": "C:\\Users\\you\\Documents\\hwinfo-reports"
      }
    }
  }
}
```

## Configuration (env vars)

| Var | Meaning | Default |
|-----|---------|---------|
| `HWINFO_EXE` | Full path to `HWiNFO64.exe` | searched in common install dirs + PATH |
| `HWINFO_REPORT_DIR` | Folder of manually-saved reports (fallback) | none |
| `HWINFO_REPORT_TIMEOUT` | Seconds to wait for a generated report | `45` |

## Verifying on Windows

1. Start HWiNFO (sensors running, Shared Memory enabled).
2. `claude mcp add hwinfo -- hwinfo-mcp`, then in Claude ask it to call `hwinfo_status`.
3. Ask for `get_live_sensors filter="cpu"` and `get_memory_timings`.

## Status / honesty

This package was written on macOS and **has not been run against real HWiNFO/hardware yet** — there's no Windows box in this environment. The shared-memory decoder follows HWiNFO's published v2 layout and is padding-tolerant; the report parser is **schema-tolerant/best-effort** because HWiNFO's exact JSON key names vary by version. If `get_memory_timings` looks thin on your machine, run `get_raw_report` and the field-name heuristics in `report.py` (`_TIMING_KEYS`) can be tightened to match.
