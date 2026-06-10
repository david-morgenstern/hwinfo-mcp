"""Reader for the HWiNFO Shared Memory v2 interface (live sensors).

HWiNFO publishes all live sensor readings (temperatures, clocks, voltages, fan
speeds, usage, power, etc.) into a named shared-memory section when "Shared
Memory Support" is enabled in HWiNFO -> Settings. We map that section read-only
and decode it with the standard library only -- no native dependency.

The public layout (well documented on the HWiNFO forum) is:

    HWiNFO_SENSORS_SHARED_MEM2 (header)
        DWORD       dwSignature           "SiWH"
        DWORD       dwVersion
        DWORD       dwRevision
        __time64_t  poll_time
        DWORD       dwOffsetOfSensorSection
        DWORD       dwSizeOfSensorElement
        DWORD       dwNumSensorElements
        DWORD       dwOffsetOfReadingSection
        DWORD       dwSizeOfReadingElement
        DWORD       dwNumReadingElements

    HWiNFO_SENSORS_SENSOR_ELEMENT      (one "group", e.g. a chip/device)
        DWORD dwSensorID; DWORD dwSensorInst;
        char  szSensorNameOrig[128]; char szSensorNameUser[128];

    HWiNFO_SENSORS_READING_ELEMENT     (one reading inside a group)
        DWORD tReading; DWORD dwSensorIndex; DWORD dwReadingID;
        char  szLabelOrig[128]; char szLabelUser[128]; char szUnit[16];
        double Value, ValueMin, ValueMax, ValueAvg;

We never hard-code element sizes: the header carries the real element strides, so
this stays correct regardless of compiler struct padding in the producing build.

NOTE (free edition): HWiNFO must be running. In the free version the Shared
Memory feature stops publishing after ~12 hours and needs HWiNFO restarted.
"""

from __future__ import annotations

import mmap
import platform
import struct

# HWiNFO tries the Global namespace first; some configs land in Local.
_MAP_NAMES = [
    "Global\\HWiNFO_SENS_SM2",
    "Local\\HWiNFO_SENS_SM2",
    "HWiNFO_SENS_SM2",
]
_SIGNATURE = b"SiWH"

_READING_TYPES = {
    0: "none",
    1: "temperature",
    2: "voltage",
    3: "fan",
    4: "current",
    5: "power",
    6: "clock",
    7: "usage",
    8: "other",
}


class SharedMemoryError(RuntimeError):
    pass


def _cstr(buf: bytes, offset: int, length: int) -> str:
    raw = buf[offset:offset + length]
    nul = raw.find(b"\x00")
    if nul != -1:
        raw = raw[:nul]
    # HWiNFO writes ANSI (current code page); cp1252 is the safe superset.
    return raw.decode("cp1252", errors="replace").strip()


def _open(name: str, length: int) -> mmap.mmap:
    # fileno=-1 + tagname opens the EXISTING named mapping created by HWiNFO,
    # provided the requested length is <= the real mapping size.
    return mmap.mmap(-1, length, tagname=name, access=mmap.ACCESS_READ)


def _open_any(length: int) -> tuple[str, mmap.mmap]:
    last: Exception | None = None
    for name in _MAP_NAMES:
        try:
            return name, _open(name, length)
        except OSError as exc:  # mapping not present under this name
            last = exc
    raise SharedMemoryError(
        "Could not open HWiNFO shared memory. Make sure HWiNFO is running and "
        "'Shared Memory Support' is enabled (Settings -> Main Settings). On the "
        "free edition it also stops after ~12h and needs a restart."
    ) from last


def _parse_header(buf: bytes) -> dict:
    if buf[0:4] != _SIGNATURE:
        raise SharedMemoryError(
            f"Unexpected shared-memory signature {buf[0:4]!r} (expected {_SIGNATURE!r})."
        )
    version, revision = struct.unpack_from("<II", buf, 4)
    # The __time64_t may sit at offset 12 (packed) or 16 (8-byte aligned).
    # Try both and keep whichever yields sane section descriptors.
    for poll_off in (16, 12):
        try:
            poll_time = struct.unpack_from("<q", buf, poll_off)[0]
            off = poll_off + 8
            (off_s, size_s, num_s,
             off_r, size_r, num_r) = struct.unpack_from("<IIIIII", buf, off)
        except struct.error:
            continue
        if (200 <= size_r <= 8192 and 200 <= size_s <= 4096
                and 0 <= num_r <= 500_000 and 0 <= num_s <= 50_000
                and off_r >= off + 24 and off_s >= off + 24):
            return {
                "version": version,
                "revision": revision,
                "poll_time": poll_time,
                "offset_sensors": off_s,
                "size_sensor": size_s,
                "num_sensors": num_s,
                "offset_readings": off_r,
                "size_reading": size_r,
                "num_readings": num_r,
            }
    raise SharedMemoryError("Could not parse HWiNFO shared-memory header layout.")


def _read_full() -> tuple[dict, bytes]:
    # Map a tiny window first to read the header, then re-map the exact size.
    name, mm = _open_any(64)
    try:
        header = _parse_header(mm[:64])
    finally:
        mm.close()
    needed = max(
        header["offset_readings"] + header["num_readings"] * header["size_reading"],
        header["offset_sensors"] + header["num_sensors"] * header["size_sensor"],
        64,
    )
    mm = _open(name, needed)
    try:
        buf = mm[:needed]
    finally:
        mm.close()
    return header, buf


def read_sensors(name_filter: str | None = None) -> dict:
    """Return all live sensor readings, optionally filtered.

    `name_filter` (case-insensitive substring) matches against either the parent
    sensor/group name or the individual reading label.
    """
    if platform.system() != "Windows":
        return {
            "ok": False,
            "error": "Shared-memory sensor reading is only available on Windows "
                     "(this is where HWiNFO runs).",
            "readings": [],
        }

    try:
        header, buf = _read_full()
    except SharedMemoryError as exc:
        return {"ok": False, "error": str(exc), "readings": []}

    # Decode the sensor groups (parents).
    groups: dict[int, str] = {}
    off_s, size_s = header["offset_sensors"], header["size_sensor"]
    for i in range(header["num_sensors"]):
        base = off_s + i * size_s
        name_user = _cstr(buf, base + 8 + 128, 128)
        name_orig = _cstr(buf, base + 8, 128)
        groups[i] = name_user or name_orig

    # Decode the readings. The four doubles always occupy the final 32 bytes of
    # an element, so locating them from the element size is padding-proof.
    off_r, size_r = header["offset_readings"], header["size_reading"]
    doubles_rel = size_r - 32
    readings = []
    needle = name_filter.lower() if name_filter else None
    for i in range(header["num_readings"]):
        base = off_r + i * size_r
        treading, sensor_index, reading_id = struct.unpack_from("<III", buf, base)
        label = _cstr(buf, base + 140, 128) or _cstr(buf, base + 12, 128)
        unit = _cstr(buf, base + 268, 16)
        value, vmin, vmax, vavg = struct.unpack_from("<dddd", buf, base + doubles_rel)
        group = groups.get(sensor_index, "")
        if needle and needle not in label.lower() and needle not in group.lower():
            continue
        readings.append({
            "sensor": group,
            "label": label,
            "type": _READING_TYPES.get(treading, "other"),
            "value": value,
            "unit": unit,
            "min": vmin,
            "max": vmax,
            "avg": vavg,
        })

    return {
        "ok": True,
        "poll_time_epoch": header["poll_time"],
        "num_groups": header["num_sensors"],
        "num_readings": len(readings),
        "total_readings": header["num_readings"],
        "readings": readings,
    }
