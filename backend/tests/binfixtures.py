"""A synthetic device log with a known layout, standing in for real (undocumented) equipment logs.

  header (64 bytes): b"DLOG" magic, u16 version, u16 record size, u32 record count, 24-byte device name,
                     28 zero bytes
  record (32 bytes, little endian):
    0  u32  unix time (seconds, +10 per record)
    4  f32  temperature (20..30)
    8  f32  humidity (40..60)
   12  u16  sequence number (+1)
   14  u8   flags (bit 0 alarm, bit 1 door open)
   15  u8   status code (0..3)
   16  4    sync bytes AA 55 AA 55
   20  i16  pressure offset (-50..50)
   22  10   zero padding
"""

import math
import struct
from pathlib import Path

HEADER = 64
RECORD = 32
T0 = 1_760_000_000
SPEC = """\
endian: little
header: 64
record_size: 32
header_fields:
  - {name: magic, offset: 0, type: str, size: 4}
  - {name: version, offset: 4, type: u16}
  - {name: device, offset: 12, type: str, size: 24}
fields:
  - {name: time, offset: 0, type: u32, time: unix_s}
  - {name: temperature, offset: 4, type: f32, unit: C}
  - {name: humidity, offset: 8, type: f32, unit: "%"}
  - {name: seq, offset: 12, type: u16}
  - {name: flags, offset: 14, type: u8, bits: {alarm: 0, door: 1}}
  - {name: status, offset: 15, type: u8}
  - {name: pressure_offset, offset: 20, type: i16, scale: 0.1, unit: hPa}
"""


def record(i: int) -> bytes:
    temp = 25 + 5 * math.sin(i / 50)
    hum = 50 + 10 * math.cos(i / 70)
    flags = (1 if i % 97 == 0 else 0) | (2 if i % 13 == 0 else 0)
    return (struct.pack("<IffHBB", T0 + 10 * i, temp, hum, i & 0xFFFF, flags, i % 4) + b"\xaa\x55\xaa\x55"
            + struct.pack("<h", (i * 7) % 101 - 50) + bytes(10))


def device_log(path: Path, n: int = 5000, device: str = "SENSOR-UNIT-07") -> Path:
    head = b"DLOG" + struct.pack("<HHI", 3, RECORD, n) + device.encode().ljust(24, b"\0") + bytes(28)
    assert len(head) == HEADER
    path.write_bytes(head + b"".join(record(i) for i in range(n)))
    return path
