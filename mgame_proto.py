"""Codec del SysEx de la M-Audio M-Game RGB Dual (ver docs/protocol.md). Solo stdlib."""
import re
from dataclasses import dataclass, field

HEADER = bytes([0xF0, 0x00, 0x01, 0x05, 0x42])
KIND_SET, KIND_GET = "set", "get"


def checksum(body: bytes) -> int:
    """body = bytes después de F0 y antes del checksum. Resultado (-suma) & 0x7F."""
    return (-(sum(body) & 0xFF)) & 0x7F


def _le32(n: int) -> bytes:
    # Los datos SysEx deben ser < 0x80. Aún no se conoce el esquema de escape de
    # la M-Game para bytes >= 0x80, así que se rechaza en vez de adivinar.
    if not isinstance(n, int) or n < 0 or n > 0xFFFFFFFF:
        raise ValueError(f"uint32 fuera de rango: {n!r}")
    b = n.to_bytes(4, "little")
    if any(x >= 0x80 for x in b):
        raise ValueError(f"0x{n:08X} tiene bytes >= 0x80 (esquema de escape desconocido)")
    return b


def _frame(payload: bytes) -> bytes:
    body = payload[1:]  # sin F0
    return payload + bytes([checksum(body), 0xF7])


def build_set(param_id: int, values, variant: int = 0) -> bytes:
    if variant not in (0, 1):  # byte 5 < 2 es la forma larga; 1 se ve en el log real
        raise ValueError("variant debe ser 0 o 1")
    values = list(values)
    if not 0 <= len(values) < 0x80:
        raise ValueError("cantidad de valores inválida")
    payload = HEADER + bytes([variant, len(values)]) + _le32(param_id)
    for v in values:
        payload += _le32(v)
    return _frame(payload)


def build_get(param_id: int, sub: int = 0) -> bytes:
    if not 0 <= sub < 0x80:
        raise ValueError("sub fuera de rango")
    return _frame(HEADER + bytes([0x02, sub]) + _le32(param_id))


@dataclass
class Message:
    kind: str                  # 'set' | 'get'
    param_id: int
    values: list = field(default_factory=list)
    count: int = 0             # N (set)
    variant: int = 0           # byte 5 de la forma set (0 o 1)
    sub: int = 0               # sub (get)

    def to_dict(self):
        d = {"kind": self.kind, "param": f"0x{self.param_id:08X}"}
        if self.kind == KIND_SET:
            d.update(count=self.count, values=[f"0x{v:08X}" for v in self.values])
        else:
            d["sub"] = self.sub
        return d


def parse(frame: bytes):
    """Devuelve Message o None si la trama es inválida."""
    frame = bytes(frame)
    if len(frame) < 13 or frame[:5] != HEADER or frame[-1] != 0xF7:
        return None
    if any(b >= 0x80 for b in frame[1:-1]):
        return None
    kind_byte = frame[5]
    if kind_byte < 2:
        n = frame[6]
        if len(frame) != 13 + 4 * n:
            return None
    elif len(frame) != 13:
        return None
    if frame[-2] != checksum(frame[1:-2]):
        return None
    param = int.from_bytes(frame[7:11], "little")
    if kind_byte < 2:
        vals = [int.from_bytes(frame[11 + 4 * i:15 + 4 * i], "little") for i in range(n)]
        return Message(KIND_SET, param, vals, count=n, variant=kind_byte)
    if kind_byte == 2:
        return Message(KIND_GET, param, sub=frame[6])
    return None


def from_hex(s: str) -> bytes:
    toks = s.split()
    if not toks or not all(re.fullmatch(r"[0-9A-Fa-f]{2}", t) for t in toks):
        raise ValueError("hex inválido")
    return bytes(int(t, 16) for t in toks)


def to_hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)
