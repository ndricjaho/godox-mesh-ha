"""Network layer and Upper Transport layer PDU construction.

Builds a single, unsegmented, unacknowledged Access-layer message
(vendor opcode + small parameter payload) all the way down into an
encrypted, obfuscated Network PDU ready to hand to the GATT Proxy
bearer. Reception (light -> us) is not implemented since none of our
commands require a response.

Per Bluetooth Mesh Profile Specification v1.0.1:
  - Section 3.4.1: Network PDU format
  - Section 3.8.7: Network layer encryption and obfuscation
  - Section 3.5.2 / 3.6: Lower/Upper Transport PDU format
  - Section 3.9: Application-layer (Upper Transport) encryption
"""
from __future__ import annotations

from dataclasses import dataclass

from . import crypto


@dataclass
class NetworkKeys:
    """Derived network-layer keys, computed once from the raw NetKey."""

    nid: int
    encryption_key: bytes
    privacy_key: bytes

    @classmethod
    def derive(cls, net_key: bytes) -> "NetworkKeys":
        nid, enc_key, priv_key = crypto.k2(net_key, b"\x00")
        return cls(nid=nid, encryption_key=enc_key, privacy_key=priv_key)


def build_access_payload(vendor_opcode_byte: int, company_id: int, params: bytes) -> bytes:
    """Build the raw Access-layer payload for a 3-octet vendor opcode message.

    A vendor opcode is encoded as: 0b11xxxxxx (top 2 bits set) | company_id
    (little-endian, 2 bytes). Company ID 0x0211 (Telink) -> bytes 11 02.
    """
    if not (0xC0 <= vendor_opcode_byte <= 0xFF):
        raise ValueError("Vendor opcode byte must be in range 0xC0-0xFF")
    opcode = bytes([vendor_opcode_byte]) + company_id.to_bytes(2, "little")
    return opcode + params


def encrypt_upper_transport(
    app_key: bytes,
    access_payload: bytes,
    seq: int,
    src: int,
    dst: int,
    iv_index: int,
) -> bytes:
    """Encrypt an Access payload with the AppKey (Upper Transport layer).

    Returns EncAccessPayload || TransMIC (4-byte MIC, since we only ever
    send small unsegmented messages).
    """
    nonce = (
        b"\x01"  # nonce type: Application
        + b"\x00"  # ASZMIC(1 bit)=0 (32-bit MIC) | RFU(7 bits)=0
        + seq.to_bytes(3, "big")
        + src.to_bytes(2, "big")
        + dst.to_bytes(2, "big")
        + iv_index.to_bytes(4, "big")
    )
    ciphertext, mic = crypto.aes_ccm_encrypt(app_key, nonce, access_payload, aad=b"", mic_len=4)
    return ciphertext + mic


def build_lower_transport_unsegmented_access(aid: int, enc_access_payload_with_mic: bytes) -> bytes:
    """Wrap an encrypted Access payload in an unsegmented Lower Transport PDU."""
    if not (0 <= aid <= 0x3F):
        raise ValueError("AID must be 6 bits (0-63)")
    header = (0 << 7) | (1 << 6) | aid  # SEG=0, AKF=1 (using an AppKey, not the DeviceKey)
    return bytes([header]) + enc_access_payload_with_mic


def encrypt_network_pdu(
    net_keys: NetworkKeys,
    lower_transport_pdu: bytes,
    seq: int,
    src: int,
    dst: int,
    iv_index: int,
    ttl: int = 5,
    ctl: int = 0,
) -> bytes:
    """Encrypt + obfuscate a full Network PDU, ready for the GATT Proxy bearer."""
    net_nonce = (
        b"\x00"  # nonce type: Network
        + bytes([(ctl << 7) | (ttl & 0x7F)])
        + seq.to_bytes(3, "big")
        + src.to_bytes(2, "big")
        + b"\x00\x00"  # padding
        + iv_index.to_bytes(4, "big")
    )
    mic_len = 8 if ctl else 4
    plaintext = dst.to_bytes(2, "big") + lower_transport_pdu
    ciphertext, net_mic = crypto.aes_ccm_encrypt(
        net_keys.encryption_key, net_nonce, plaintext, aad=b"", mic_len=mic_len
    )

    # Privacy obfuscation of (CTL/TTL || SEQ || SRC).
    privacy_random = (
        b"\x00\x00\x00\x00\x00"
        + iv_index.to_bytes(4, "big")
        + (ciphertext + net_mic)[:7]
    )
    pecb = crypto.aes_ecb_encrypt(net_keys.privacy_key, privacy_random)[:6]

    header_plain = bytes([(ctl << 7) | (ttl & 0x7F)]) + seq.to_bytes(3, "big") + src.to_bytes(2, "big")
    obfuscated = bytes(a ^ b for a, b in zip(header_plain, pecb))

    ivi_nid = ((iv_index & 0x01) << 7) | net_keys.nid
    return bytes([ivi_nid]) + obfuscated + ciphertext + net_mic


def build_message(
    net_key: bytes,
    app_key: bytes,
    src: int,
    dst: int,
    seq: int,
    iv_index: int,
    vendor_opcode_byte: int,
    company_id: int,
    params: bytes,
    ttl: int = 5,
) -> bytes:
    """End-to-end: build a fully encrypted Network PDU for one vendor command."""
    access_payload = build_access_payload(vendor_opcode_byte, company_id, params)
    enc_access = encrypt_upper_transport(app_key, access_payload, seq, src, dst, iv_index)
    aid = crypto.k4(app_key)
    lower_transport = build_lower_transport_unsegmented_access(aid, enc_access)
    net_keys = NetworkKeys.derive(net_key)
    return encrypt_network_pdu(net_keys, lower_transport, seq, src, dst, iv_index, ttl=ttl)
