"""GATT Proxy bearer PDU framing.

Per Mesh Profile Specification v1.0.1 Section 6.3.2.2 (Proxy PDU), every
write to the "Mesh Proxy Data In" characteristic is prefixed with one
header byte: SAR (2 bits) | Message Type (6 bits). Message Type 0x00 is
"Network PDU". If the Network PDU + header doesn't fit in one ATT write
(ATT_MTU - 3 bytes), it must be segmented (SAR = 0b01 first, 0b10
continuation, 0b11 last; 0b00 means "complete message, no segmentation
needed").

We only ever send small messages (well under 30 bytes), so segmentation
is rarely needed in practice, but it's implemented properly so this
doesn't silently break against a connection that negotiated a small
ATT MTU (e.g. the BLE 4.0/4.1 default of 23 bytes total / 20 usable).
"""
from __future__ import annotations

SAR_COMPLETE = 0b00
SAR_FIRST = 0b01
SAR_CONTINUATION = 0b10
SAR_LAST = 0b11

MSG_TYPE_NETWORK_PDU = 0x00


def frame_network_pdu(network_pdu: bytes, att_mtu: int) -> list[bytes]:
    """Split a Network PDU into one or more GATT Proxy PDU writes.

    att_mtu is the negotiated ATT_MTU; each write can carry at most
    (att_mtu - 3) bytes total, 1 of which is our header byte.
    """
    max_chunk = max(att_mtu - 3 - 1, 1)
    if len(network_pdu) <= max_chunk:
        header = (SAR_COMPLETE << 6) | MSG_TYPE_NETWORK_PDU
        return [bytes([header]) + network_pdu]

    chunks = [network_pdu[i : i + max_chunk] for i in range(0, len(network_pdu), max_chunk)]
    frames = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            sar = SAR_FIRST
        elif i == len(chunks) - 1:
            sar = SAR_LAST
        else:
            sar = SAR_CONTINUATION
        header = (sar << 6) | MSG_TYPE_NETWORK_PDU
        frames.append(bytes([header]) + chunk)
    return frames


class ProxyPduReassembler:
    """Reassembles notifications from "Mesh Proxy Data Out" back into PDUs.

    Not currently used (we don't parse responses), kept for completeness
    and for anyone extending this to read status messages back.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._in_progress = False

    def feed(self, data: bytes) -> tuple[int, bytes] | None:
        if not data:
            return None
        sar = (data[0] >> 6) & 0b11
        msg_type = data[0] & 0b111111
        payload = data[1:]

        if sar == SAR_COMPLETE:
            return msg_type, payload
        if sar == SAR_FIRST:
            self._buffer = bytearray(payload)
            self._in_progress = True
            return None
        if sar == SAR_CONTINUATION:
            if self._in_progress:
                self._buffer.extend(payload)
            return None
        if sar == SAR_LAST:
            if self._in_progress:
                self._buffer.extend(payload)
                self._in_progress = False
                return msg_type, bytes(self._buffer)
        return None
