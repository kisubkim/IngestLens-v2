"""Overview of a binary file (device logs and other undocumented formats) for an LLM that works out the format.

The overview is small (tens of KB) whatever the file size: file facts, the header as a hex dump, the most likely
fixed record length and header size, per-offset findings inside a record (constant bytes, counters, timestamps,
plausible floats), sample records, and strings with their offsets. The LLM reads it, writes a format spec
(tools/binspec.py) and the code decodes the whole file; the LLM never has to read megabytes of hex.
"""

import hashlib
import math
import re
from pathlib import Path

import filetype
import numpy as np

HEADER_BYTES = 512
PERIOD_SAMPLE = 64 * 1024
MAX_PERIOD = 4096
MAX_RECORDS = 50_000  # records analysed per column
MAX_FIELD_SCAN = 1024  # longer records get only the constant-byte scan
STRINGS_SHOWN = 60
ASCII_RX = re.compile(rb"[\x20-\x7e]{6,}")
UTF16_RX = re.compile(rb"(?:[\x20-\x7e]\x00){6,}")


def hexdump(data: bytes, start: int = 0, width: int = 16) -> str:
    """xxd style: offset, hex bytes, printable ASCII."""
    lines = []
    for i in range(0, len(data), width):
        row = data[i:i + width]
        hexes = " ".join(f"{b:02x}" for b in row).ljust(width * 3 - 1)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{start + i:08x}  {hexes}  |{text}|")
    return "\n".join(lines)


def entropy(a: np.ndarray) -> float:
    """Shannon entropy in bits per byte (0 = constant, 8 = random/compressed/encrypted)."""
    if not len(a):
        return 0.0
    p = np.bincount(a, minlength=256) / len(a)
    p = p[p > 0]
    return round(float(-(p * np.log2(p)).sum()), 2)


def find_period(a: np.ndarray) -> dict:
    """The most likely fixed record length: the shift p at which bytes repeat most (data[i] == data[i + p]).
    Multiples of the record length score as high, so the smallest length near the best score wins."""
    if len(a) < 64:
        return {"record_size": None, "confidence": 0.0, "candidates": []}
    # Sample from a quarter into the file, past any header.
    start = len(a) // 4 if len(a) > 4 * PERIOD_SAMPLE else 0
    s = a[start:start + PERIOD_SAMPLE]
    top = min(MAX_PERIOD, len(s) // 4)
    if top < 2:
        return {"record_size": None, "confidence": 0.0, "candidates": []}
    scores = np.array([np.count_nonzero(s[:-p] == s[p:]) / (len(s) - p) for p in range(1, top + 1)])
    base = float(np.median(scores))
    best = float(scores.max())
    if best - base < 0.1:
        return {"record_size": None, "confidence": 0.0, "baseline": round(base, 3), "candidates": []}
    near = [p for p in range(2, top + 1) if scores[p - 1] >= base + 0.9 * (best - base)]
    p = near[0] if near else int(scores.argmax()) + 1
    ranked = sorted(range(2, top + 1), key=lambda q: -scores[q - 1])[:5]
    return {"record_size": p, "match_rate": round(float(scores[p - 1]), 3), "baseline": round(base, 3),
            "confidence": round((float(scores[p - 1]) - base) / max(1e-9, 1 - base), 2),
            "candidates": [{"size": q, "match_rate": round(float(scores[q - 1]), 3)} for q in ranked]}


def find_header(a: np.ndarray, p: int) -> dict:
    """The header size: records are aligned so that whole records reach the end of the file (offsets = size mod p),
    and the first record is the first aligned block whose constant bytes match the records in the middle of the
    file (e.g. a sync marker). Without constant bytes, the start of the repeating region is used."""
    size = len(a)
    rem = size % p
    periodic_from = _periodic_start(a, p)
    # Aligned records spread over the last 90% of the file (past any header): bytes constant in all of them.
    first_k, last_k = (size // 10 - rem) // p + 1, (size - rem) // p - 1
    ks = np.unique(np.linspace(first_k, last_k, num=min(2000, max(0, last_k - first_k + 1))).astype(np.int64))
    n_mid = len(ks)
    if n_mid >= 8:
        rec = np.stack([a[rem + k * p:rem + (k + 1) * p] for k in ks])
        cols = np.flatnonzero((rec == rec[0]).all(axis=0))
        if len(cols):
            # Bytes constant in the middle of the file may still vary over the whole file (the high bytes of a
            # timestamp), so the first record is the first aligned block that matches nearly as well as the best.
            want = rec[0, cols]
            hs = list(range(rem, min(size - 4 * p, 64 * 1024) + 1, p))
            scores = [float((a[h:h + 4 * p].reshape(4, p)[:, cols] == want).mean()) for h in hs]
            if scores and max(scores) >= 0.8:
                bar = max(scores) - 0.03
                h = next(h for h, sc in zip(hs, scores) if sc >= bar)
                return {"periodic_from": periodic_from, "header_size": h, "fits_eof": True, "method": "constant bytes"}
    k = max(0, round((periodic_from - rem) / p))
    return {"periodic_from": periodic_from, "header_size": rem + k * p, "fits_eof": True, "method": "repeat start"}


def _periodic_start(a: np.ndarray, p: int) -> int:
    n = min(len(a) - p, 256 * 1024)
    if n <= 0:
        return 0
    m = (a[:n] == a[p:p + n]).astype(np.float32)
    win = max(p * 4, 64)
    if n <= win:
        return 0
    roll = np.convolve(m, np.ones(win) / win, mode="valid")
    level = (roll.max() + np.median(roll)) / 2
    return int(np.argmax(roll >= level))


def _monotonic_share(v: np.ndarray) -> float:
    d = np.diff(v.astype(np.float64))
    return float(np.count_nonzero(d >= 0) / len(d)) if len(d) else 0.0


def analyse_fields(a: np.ndarray, header: int, p: int) -> dict:
    """Per-offset findings inside a record: constant bytes, increasing counters/timestamps, plausible floats."""
    n = min((len(a) - header) // p, MAX_RECORDS)
    if n < 4:
        return {"records_analysed": n, "constant": [], "findings": []}
    rec = a[header:header + n * p].reshape(n, p)
    const = []
    for j in range(p):
        col = rec[:, j]
        if (col == col[0]).all():
            if const and const[-1]["end"] == j - 1:
                const[-1]["end"] = j
                const[-1]["bytes"] += f" {col[0]:02x}"
            else:
                const.append({"start": j, "end": j, "bytes": f"{col[0]:02x}"})

    findings = []
    if p > MAX_FIELD_SCAN:
        return {"records_analysed": n, "constant": const, "findings": []}
    for size, kinds in ((2, ("u16",)), (4, ("u32", "f32")), (8, ("u64", "f64"))):
        for j in range(0, p - size + 1):
            cols = np.ascontiguousarray(rec[:, j:j + size]).view(np.uint8).reshape(n, size)
            if (cols == cols[0]).all():
                continue  # constant: listed above
            for endian in ("<", ">"):
                for kind in kinds:
                    dt = np.dtype(endian + {"u16": "u2", "u32": "u4", "u64": "u8", "f32": "f4", "f64": "f8"}[kind])
                    v = cols.copy().view(dt).reshape(n)
                    f = _judge(kind, v)
                    if f:
                        findings.append({"offset": j, "type": kind, "endian": "little" if endian == "<" else "big", **f})
    # Fields do not overlap: take aligned, little-endian, most telling findings first and drop any that overlap
    # one already taken (a u32 read across a timestamp and a float looks like a counter too).
    rank = {"timestamp": 0, "counter": 1, "float": 2}
    width = {"u16": 2, "u32": 4, "f32": 4, "u64": 8, "f64": 8}
    taken: list[dict] = []
    for f in sorted(findings, key=lambda f: (f["offset"] % width[f["type"]] != 0, f["endian"] != "little",
                                             rank[f["kind"]], width[f["type"]] if f["kind"] == "float" else -width[f["type"]],
                                             -f.get("monotonic", 0))):
        lo, hi = f["offset"], f["offset"] + width[f["type"]]
        if any(lo < t["offset"] + width[t["type"]] and t["offset"] < hi for t in taken):
            continue
        taken.append(f)
    return {"records_analysed": n, "constant": const, "findings": sorted(taken, key=lambda f: f["offset"])[:40]}


def _judge(kind: str, v: np.ndarray) -> dict | None:
    if kind.startswith("f"):
        if not np.isfinite(v).all():
            return None
        lo, hi = float(v.min()), float(v.max())
        if max(abs(lo), abs(hi)) > 1e7 or (0 < max(abs(lo), abs(hi)) < 1e-6) or lo == hi:
            return None
        if np.allclose(v, np.round(v)) and max(abs(lo), abs(hi)) > 1e4:
            return None  # an integer field read as float
        return {"kind": "float", "min": round(lo, 4), "max": round(hi, 4), "mean": round(float(v.mean()), 4)}
    mono = _monotonic_share(v)
    lo, hi = int(v.min()), int(v.max())
    if mono >= 0.99 and hi > lo:
        if kind == "u32" and 946684800 <= lo and hi <= 4102444800:  # 2000-01-01 .. 2100-01-01 in seconds
            return {"kind": "timestamp", "unit": "unix seconds", "min": lo, "max": hi, "monotonic": round(mono, 3)}
        if kind == "u64" and 946684800_000 <= lo and hi <= 4102444800_000:
            return {"kind": "timestamp", "unit": "unix milliseconds", "min": lo, "max": hi, "monotonic": round(mono, 3)}
        steps = np.diff(v.astype(np.int64))
        step = int(np.median(steps)) if len(steps) else 0
        if 0 < step <= 1_000_000:
            return {"kind": "counter", "min": lo, "max": hi, "step": step, "monotonic": round(mono, 3)}
    return None


def strings(data: bytes) -> list[dict]:
    out = [{"offset": m.start(), "text": m.group().decode("ascii")} for m in ASCII_RX.finditer(data)]
    out += [{"offset": m.start(), "text": m.group().decode("utf-16-le"), "encoding": "utf-16le"} for m in UTF16_RX.finditer(data)]
    return sorted(out, key=lambda s: s["offset"])


def analyse(path: Path) -> dict:
    data = Path(path).read_bytes()
    a = np.frombuffer(data, dtype=np.uint8)
    kind = filetype.guess(data[:8192])
    blocks = [entropy(a[i:i + 65536]) for i in range(0, len(a), 65536)] or [0.0]
    out = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
           "magic": kind.mime if kind else None, "entropy": entropy(a),
           "block_entropy": {"min": min(blocks), "max": max(blocks), "blocks": len(blocks)},
           "header_hex": hexdump(data[:HEADER_BYTES]), "strings": strings(data)}
    period = find_period(a)
    out["period"] = period
    p = period.get("record_size")
    if p:
        hdr = find_header(a, p)
        out["layout"] = hdr
        out["fields"] = analyse_fields(a, hdr["header_size"], p)
        h, n = hdr["header_size"], (len(a) - hdr["header_size"]) // p
        picks = sorted({0, 1, 2, n // 2, n - 1} & set(range(n)))
        out["sample_records"] = [{"index": i, "offset": h + i * p, "hex": hexdump(data[h + i * p:h + (i + 1) * p], h + i * p)}
                                 for i in picks]
    return out


SPEC_HELP = """\
Format spec (YAML) for the decode tools:
  endian: little | big            # default for all fields
  header: <bytes before the first record>
  record_size: <bytes per record>
  count: <records, optional; default: as many as fit before end of file>
  header_fields: [<field>, ...]   # optional, offsets from the start of the file
  fields: [<field>, ...]          # offsets from the start of each record
  <field>: {name: temp, offset: 4, type: f32}
    type: u8 i8 u16 i16 u32 i32 u64 i64 f32 f64 | str (with size, encoding) | bytes (with size)
    optional: endian, scale (value * scale + add), add, unit, time: unix_s | unix_ms (shown as ISO time),
              bits: {alarm: 0, door: 1}  (named bits of an integer field)
"""


def overview_text(name: str, doc_id: str, info: dict) -> str:
    """The overview as plain text (ASCII, drawn in a monospace font)."""
    lines = [f"BINARY FILE OVERVIEW: {name}", f"document_id: {doc_id}",
             f"size: {info['size']} bytes   sha256: {info['sha256']}",
             f"magic: {info['magic'] or 'unknown (no known file signature)'}",
             f"entropy: {info['entropy']} bits/byte (block min {info['block_entropy']['min']}, max {info['block_entropy']['max']}; "
             "near 8 = compressed or encrypted)", ""]
    per = info["period"]
    lines.append("RECORD STRUCTURE")
    if per.get("record_size"):
        lay = info["layout"]
        lines += [f"likely fixed record size: {per['record_size']} bytes (repeat rate {per['match_rate']}, baseline {per['baseline']}, "
                  f"confidence {per['confidence']})",
                  "other candidates: " + ", ".join(f"{c['size']} ({c['match_rate']})" for c in per["candidates"]),
                  f"header size: {lay['header_size']} bytes (first record found by {lay['method']}"
                  + (")" if lay["method"] == "constant bytes" else f"; a guess: repeating data starts near offset {lay['periodic_from']})"),
                  f"records: {(info['size'] - lay['header_size']) // per['record_size']}", ""]
        f = info["fields"]
        lines.append(f"FIELDS INSIDE A RECORD (offsets from record start, {f['records_analysed']} records analysed)")
        for c in f["constant"]:
            span = f"{c['start']}" if c["start"] == c["end"] else f"{c['start']}-{c['end']}"
            lines.append(f"  offset {span}: constant {c['bytes'][:60]}")
        for x in f["findings"]:
            if x["kind"] == "timestamp":
                desc = f"timestamp ({x['unit']}) {x['min']}..{x['max']}"
            elif x["kind"] == "counter":
                desc = f"increasing counter {x['min']}..{x['max']} step {x['step']}"
            else:
                desc = f"plausible float {x['min']}..{x['max']} mean {x['mean']}"
            lines.append(f"  offset {x['offset']}: {x['type']} {x['endian']}: {desc}")
        if not f["constant"] and not f["findings"]:
            lines.append("  (no constant bytes, counters or plausible floats found)")
        lines.append("")
        lines.append("SAMPLE RECORDS")
        for r in info["sample_records"]:
            lines += [f"record {r['index']} (offset {r['offset']}):", r["hex"]]
        lines.append("")
    else:
        lines += ["no fixed record size found (variable-length records, text, or compressed data)", ""]
    lines += [f"HEADER (first {min(HEADER_BYTES, info['size'])} bytes)", info["header_hex"], ""]
    s = info["strings"]
    lines.append(f"STRINGS ({len(s)} found, first {min(len(s), STRINGS_SHOWN)} shown: offset, text)")
    for x in s[:STRINGS_SHOWN]:
        lines.append(f"  {x['offset']:08x} {x['text'][:100]}" + ("  (utf-16le)" if x.get("encoding") else ""))
    lines += ["", SPEC_HELP]
    return "\n".join(lines) + "\n"
