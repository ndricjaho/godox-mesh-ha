"""Persistent Bluetooth Mesh sequence number counter.

The sequence number is part of every encryption nonce. Reusing a
(src, seq, iv_index) tuple breaks AES-CCM's security guarantees, so this
must NEVER reset to a lower value than it's already reached -- including
across Home Assistant restarts. It's shared across every light this
integration controls (it belongs to the sending node, i.e. us, not to
each light individually).

Stored as plain JSON via Home Assistant's storage helpers by the calling
code; this class only holds the in-memory counter and increment logic so
it can be unit tested without a running HA instance.
"""
from __future__ import annotations

MAX_SEQ = 0xFFFFFF  # 24-bit


class SequenceCounter:
    def __init__(self, start: int = 0) -> None:
        if not (0 <= start <= MAX_SEQ):
            raise ValueError("seq out of range")
        self._value = start

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        """Return the next sequence number to use, and advance the counter."""
        if self._value >= MAX_SEQ:
            # 24-bit SEQ exhausted. A real implementation would trigger an
            # IV Index update procedure here; for a single low-traffic
            # light this should realistically take years to hit, so we
            # just refuse rather than silently wrap (wrapping would reuse
            # nonces, which is the one thing we must never do).
            raise RuntimeError(
                "Mesh sequence number exhausted (24-bit limit reached). "
                "An IV Index update is required; this is not implemented."
            )
        seq = self._value
        self._value += 1
        return seq

    def to_dict(self) -> dict:
        return {"seq": self._value}

    @classmethod
    def from_dict(cls, data: dict) -> "SequenceCounter":
        return cls(start=int(data.get("seq", 0)))
