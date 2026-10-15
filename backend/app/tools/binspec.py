"""Decode a binary file with a format spec (YAML): header fields plus fixed-length records. The LLM writes the spec
from the overview (tools/binview.py); this code reads every record exactly (numpy), checks the result for signs
of a wrong guess, answers value lookups and exports JSON. The spec format is described in binview.SPEC_HELP.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

NUMERIC = {"u8": "u1", "i8": "i1", "u16": "u2", "i16": "i2", "u32": "u4", "i32": "i4", "u64": "u8", "i64": "i8",
           "f32": "f4", "f64": "f8"}
TEXT_TYPES = {"str", "bytes"}
FIELD_KEYS = {"name", "offset", "type", "size", "endian", "scale", "add", "unit", "time", "bits", "encoding", "description"}
SPEC_KEYS = {"endian", "header", "record_size", "count", "header_fields", "fields", "name", "description"}
TIME_UNITS = {"unix_s": 1, "unix_ms": 1000}
EPOCH_MIN, EPOCH_MAX = 946684800, 4102444800  # 2000-01-01 .. 2100-01-01


class SpecError(ValueError):
    """The spec cannot be used; the message says what to change."""


def _field(f, where: str, endian: str) -> dict:
    if not isinstance(f, dict):
        raise SpecError(f"{where}: each field is a mapping like {{name: temp, offset: 4, type: f32}}")
    if unknown := set(f) - FIELD_KEYS:
        raise SpecError(f"{where}: unknown keys {sorted(unknown)}; allowed: {sorted(FIELD_KEYS)}")
    name, typ = f.get("name"), f.get("type")
    if not isinstance(name, str) or not name:
        raise SpecError(f"{where}: name is missing")
    if typ not in NUMERIC and typ not in TEXT_TYPES:
        raise SpecError(f"{where} ({name}): type {typ!r} is not one of {sorted(NUMERIC) + sorted(TEXT_TYPES)}")
    off = f.get("offset")
    if not isinstance(off, int) or off < 0:
        raise SpecError(f"{where} ({name}): offset must be a byte offset (integer >= 0)")
    e = f.get("endian", endian)
    if e not in ("little", "big"):
        raise SpecError(f"{where} ({name}): endian must be little or big")
    if typ in TEXT_TYPES:
        size = f.get("size")
        if not isinstance(size, int) or size <= 0:
            raise SpecError(f"{where} ({name}): {typ} needs size (bytes)")
    else:
        size = int(NUMERIC[typ][1])
        if f.get("size") not in (None, size):
            raise SpecError(f"{where} ({name}): {typ} is {size} bytes; drop size or change the type")
    if f.get("time") is not None and (f["time"] not in TIME_UNITS or typ in TEXT_TYPES or typ.startswith("f")):
        raise SpecError(f"{where} ({name}): time is unix_s or unix_ms on an integer field")
    bits = f.get("bits")
    if bits is not None:
        if typ not in NUMERIC or typ.startswith("f") or not isinstance(bits, dict):
            raise SpecError(f"{where} ({name}): bits is {{flag_name: bit_number}} on an integer field")
        for k, b in bits.items():
            if not isinstance(b, int) or not 0 <= b < size * 8:
                raise SpecError(f"{where} ({name}): bit {k}={b!r} is outside 0..{size * 8 - 1}")
    for k in ("scale", "add"):
        if f.get(k) is not None and not isinstance(f[k], (int, float)):
            raise SpecError(f"{where} ({name}): {k} must be a number")
    return {**f, "endian": e, "size": size, "encoding": f.get("encoding", "ascii")}


def parse_spec(spec) -> dict:
    """YAML text or a mapping -> a checked spec. Raises SpecError with a message meant for the spec's author."""
    if isinstance(spec, str):
        try:
            spec = yaml.safe_load(spec)
        except yaml.YAMLError as e:
            raise SpecError(f"the spec is not valid YAML: {e}") from None
    if not isinstance(spec, dict):
        raise SpecError("the spec must be a YAML mapping with record_size and fields")
    if unknown := set(spec) - SPEC_KEYS:
        raise SpecError(f"unknown top-level keys {sorted(unknown)}; allowed: {sorted(SPEC_KEYS)}")
    endian = spec.get("endian", "little")
    if endian not in ("little", "big"):
        raise SpecError("endian must be little or big")
    header, rsize, count = spec.get("header", 0), spec.get("record_size"), spec.get("count")
    if not isinstance(header, int) or header < 0:
        raise SpecError("header must be the number of bytes before the first record (integer >= 0)")
    fields = spec.get("fields") or []
    if fields and (not isinstance(rsize, int) or rsize <= 0):
        raise SpecError("record_size (bytes per record, integer > 0) is needed with fields")
    if count is not None and (not isinstance(count, int) or count < 0):
        raise SpecError("count must be an integer >= 0, or left out")
    out_fields = [_field(f, f"fields[{i}]", endian) for i, f in enumerate(fields)]
    for f in out_fields:
        if f["offset"] + f["size"] > rsize:
            raise SpecError(f"field {f['name']}: offset {f['offset']} + size {f['size']} is past record_size {rsize}")
    hfields = [_field(f, f"header_fields[{i}]", endian) for i, f in enumerate(spec.get("header_fields") or [])]
    names = [f["name"] for f in out_fields]
    if len(set(names)) != len(names):
        raise SpecError("field names must be unique")
    if not out_fields and not hfields:
        raise SpecError("the spec has no fields")
    return {"endian": endian, "header": header, "record_size": rsize, "count": count, "fields": out_fields,
            "header_fields": hfields}


def _dtype(f: dict) -> str:
    if f["type"] in TEXT_TYPES:
        return f"S{f['size']}"
    return ("<" if f["endian"] == "little" else ">") + NUMERIC[f["type"]]


def layout(spec: dict, size: int) -> dict:
    avail = max(0, (size - spec["header"]) // spec["record_size"]) if spec["record_size"] else 0
    count = avail if spec["count"] is None else min(spec["count"], avail)
    used = spec["header"] + count * (spec["record_size"] or 0)
    return {"available": avail, "count": count, "trailing_bytes": size - used}


def _array(data: memoryview, spec: dict, start: int, count: int) -> np.ndarray:
    fs = spec["fields"]
    dt = np.dtype({"names": [f["name"] for f in fs], "formats": [_dtype(f) for f in fs],
                   "offsets": [f["offset"] for f in fs], "itemsize": spec["record_size"]})
    off = spec["header"] + start * spec["record_size"]
    return np.frombuffer(data, dtype=dt, count=count, offset=off)


def _value(f: dict, v):
    """One raw value -> JSON value (scaled number, ISO time, text, hex bytes, or a bit mapping)."""
    if f["type"] == "str":
        return bytes(v).split(b"\0", 1)[0].decode(f["encoding"], errors="replace")
    if f["type"] == "bytes":
        return bytes(v).hex(" ")
    if f["type"] == "f32":
        v = float(str(np.float32(v)))  # shortest form: 25.1, not 25.099992752075195
    v = v.item() if hasattr(v, "item") else v
    if f.get("time"):
        secs = v / TIME_UNITS[f["time"]]
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return f"invalid time {v}"
    if f.get("bits"):
        return {"value": v, **{k: bool((v >> b) & 1) for k, b in f["bits"].items()}}
    if f.get("scale") is not None or f.get("add") is not None:
        v = v * (f.get("scale") if f.get("scale") is not None else 1) + (f.get("add") or 0)
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    return v


def header_values(data: memoryview, spec: dict) -> dict:
    out = {}
    for f in spec["header_fields"]:
        if f["offset"] + f["size"] > len(data):
            out[f["name"]] = "past end of file"
            continue
        v = np.frombuffer(data, dtype=np.dtype(_dtype(f)), count=1, offset=f["offset"])[0]
        out[f["name"]] = _value(f, v)
    return out


def records(path: Path, spec: dict, start: int, count: int, fields: list[str] | None = None) -> dict:
    """Records start..start+count-1 as JSON values (fields: only these names)."""
    data = memoryview(Path(path).read_bytes())
    lay = layout(spec, len(data))
    start = max(0, start)
    count = max(0, min(count, lay["count"] - start))
    fs = [f for f in spec["fields"] if not fields or f["name"] in fields]
    if fields and (missing := set(fields) - {f["name"] for f in spec["fields"]}):
        raise SpecError(f"unknown fields {sorted(missing)}; the spec has {[f['name'] for f in spec['fields']]}")
    arr = _array(data, spec, start, count) if count else []
    out = [{"index": start + i, "offset": spec["header"] + (start + i) * spec["record_size"],
            **{f["name"]: _value(f, row[f["name"]]) for f in fs}} for i, row in enumerate(arr)]
    return {"total_records": lay["count"], "records": out}


def _stats(f: dict, col: np.ndarray) -> dict:
    """Numbers a reader uses to judge a guess: range, NaNs, how often it increases, the other byte order's range."""
    if f["type"] in TEXT_TYPES:
        vals = [bytes(v).split(b"\0", 1)[0] for v in col[:2000]]
        printable = sum(all(32 <= c < 127 for c in v) for v in vals) / max(1, len(vals))
        return {"printable_share": round(printable, 3), "distinct_in_first_2000": len(set(vals))}
    with np.errstate(invalid="ignore", over="ignore"):
        x = col.astype(np.float64)
    finite = np.isfinite(x)
    s: dict = {"nan_or_inf": int((~finite).sum())}
    x = x[finite]
    if not len(x):
        return s
    s |= {"min": float(x.min()), "max": float(x.max()), "mean": round(float(x.mean()), 6),
          "distinct": int(len(np.unique(x[:200_000])))}
    if len(x) > 1:
        d = np.diff(x)
        s["increasing_share"] = round(float((d >= 0).mean()), 3)
    if f["size"] > 1:
        with np.errstate(invalid="ignore", over="ignore"):
            other = np.ascontiguousarray(col).view(col.dtype.newbyteorder()).astype(np.float64)
        other = other[np.isfinite(other)]
        if len(other):
            s["if_other_endian"] = {"min": float(other.min()), "max": float(other.max())}
    return s


def decode(path: Path, spec: dict, preview: int = 5) -> dict:
    """Decode every record and report: layout, header values, per-field statistics, warnings, first records."""
    data = memoryview(Path(path).read_bytes())
    lay = layout(spec, len(data))
    warnings = []
    if spec["header"] > len(data):
        raise SpecError(f"header {spec['header']} is larger than the file ({len(data)} bytes)")
    if lay["trailing_bytes"] and spec["count"] is None:
        warnings.append(f"{lay['trailing_bytes']} bytes left after the last whole record: record_size or header may be "
                        f"wrong, or the file has a trailer (size {len(data)}, header {spec['header']}, "
                        f"record_size {spec['record_size']})")
    if spec["count"] is not None and spec["count"] > lay["available"]:
        warnings.append(f"count {spec['count']} but only {lay['available']} whole records fit in the file")
    spans = sorted((f["offset"], f["offset"] + f["size"], f["name"]) for f in spec["fields"])
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        if b0 < a1:
            warnings.append(f"fields {an} and {bn} overlap (bytes {b0}..{a1 - 1})")
    stats = {}
    arr = _array(data, spec, 0, lay["count"]) if lay["count"] and spec["fields"] else None
    for f in spec["fields"]:
        if arr is None:
            break
        s = _stats(f, arr[f["name"]])
        stats[f["name"]] = s
        if s.get("nan_or_inf"):
            warnings.append(f"{f['name']}: {s['nan_or_inf']} NaN/inf values; maybe not a float, or the other byte order")
        if f.get("time") and "min" in s:
            lo, hi = s["min"] / TIME_UNITS[f["time"]], s["max"] / TIME_UNITS[f["time"]]
            if lo < EPOCH_MIN or hi > EPOCH_MAX:
                warnings.append(f"{f['name']}: times outside 2000..2100 ({lo:.0f}..{hi:.0f} s); wrong offset, unit or byte order?")
            if s.get("increasing_share", 1) < 0.95:
                warnings.append(f"{f['name']}: time goes backwards in {1 - s['increasing_share']:.0%} of steps")
        if f["type"].startswith("f") and "min" in s and max(abs(s["min"]), abs(s["max"])) > 1e9:
            warnings.append(f"{f['name']}: floats up to {max(abs(s['min']), abs(s['max'])):.3g}; maybe an integer field")
        if f["type"] in TEXT_TYPES and s.get("printable_share", 1) < 0.9 and f["type"] == "str":
            warnings.append(f"{f['name']}: only {s['printable_share']:.0%} of values are printable text")
    first = records(path, spec, 0, preview)["records"] if lay["count"] and spec["fields"] else []
    return {"file_size": len(data), "header_size": spec["header"], "record_size": spec["record_size"],
            "records": lay["count"], "trailing_bytes": lay["trailing_bytes"], "header": header_values(data, spec),
            "field_stats": stats, "warnings": warnings, "first_records": first, "ok": not warnings}


def export_json(path: Path, spec: dict, out: Path, block: int = 20_000) -> dict:
    """The whole file as {"header": {...}, "records": [...]}, written in blocks so large logs fit in memory."""
    data = memoryview(Path(path).read_bytes())
    lay = layout(spec, len(data))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write('{"header": ' + json.dumps(header_values(data, spec), ensure_ascii=False) + ', "records": [')
        for start in range(0, lay["count"], block):
            arr = _array(data, spec, start, min(block, lay["count"] - start))
            rows = [{f["name"]: _value(f, row[f["name"]]) for f in spec["fields"]} for row in arr]
            body = ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            fh.write(("\n" if start == 0 else ",\n") + body)
        fh.write("\n]}\n")
    tmp.replace(out)
    return {"records": lay["count"], "bytes": out.stat().st_size}
