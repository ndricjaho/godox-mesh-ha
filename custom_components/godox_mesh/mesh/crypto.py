"""Bluetooth Mesh cryptographic primitives.

Implements the key-derivation and encryption functions defined in the
Bluetooth Mesh Profile Specification v1.0.1, Section 3.8 (key derivation)
and Section 3.9 (message integrity and encryption). Only the pieces
needed to talk to a single already-provisioned node over the GATT Proxy
bearer are implemented (no provisioning, no relay/friend logic).

References throughout are to the Mesh Profile Specification v1.0.1.
"""
from __future__ import annotations

from Crypto.Cipher import AES
from Crypto.Hash import CMAC


ZERO_KEY = b"\x00" * 16


def aes_cmac(key: bytes, message: bytes) -> bytes:
    """AES-CMAC-128, per RFC 4493."""
    c = CMAC.new(key, ciphermod=AES)
    c.update(message)
    return c.digest()


def aes_ecb_encrypt(key: bytes, plaintext_block: bytes) -> bytes:
    """Single-block AES-128-ECB encrypt (the "e" function in the spec)."""
    assert len(plaintext_block) == 16
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext_block)


def s1(m: bytes) -> bytes:
    """Salt generation function s1(M) = AES-CMAC_zero(M)."""
    return aes_cmac(ZERO_KEY, m)


def k1(n: bytes, salt: bytes, p: bytes) -> bytes:
    """k1(N, SALT, P) = AES-CMAC_T(P), T = AES-CMAC_SALT(N)."""
    t = aes_cmac(salt, n)
    return aes_cmac(t, p)


def k2(n: bytes, p: bytes) -> tuple[int, bytes, bytes]:
    """k2(N, P) -> (NID, EncryptionKey, PrivacyKey).

    Used to derive the network-layer keys from a NetKey (P = 0x00).
    """
    salt = s1(b"smk2")
    t = aes_cmac(salt, n)
    t1 = aes_cmac(t, p + b"\x01")
    t2 = aes_cmac(t, t1 + p + b"\x02")
    t3 = aes_cmac(t, t2 + p + b"\x03")
    nid = t1[-1] & 0x7F
    encryption_key = t2
    privacy_key = t3
    return nid, encryption_key, privacy_key


def k3(n: bytes) -> bytes:
    """k3(N) -> 64-bit Network ID."""
    salt = s1(b"smk3")
    t = aes_cmac(salt, n)
    full = aes_cmac(t, b"id64" + b"\x01")
    return full[-8:]


def k4(n: bytes) -> int:
    """k4(N) -> 6-bit AID (application key identifier)."""
    salt = s1(b"smk4")
    t = aes_cmac(salt, n)
    full = aes_cmac(t, b"id6" + b"\x01")
    return full[-1] & 0x3F


# ---------------------------------------------------------------------------
# AES-CCM (only what we need: single-block-friendly, small payloads)
# ---------------------------------------------------------------------------

def aes_ccm_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes, mic_len: int) -> tuple[bytes, bytes]:
    """AES-CCM encrypt. Returns (ciphertext, mic)."""
    cipher = AES.new(key, AES.MODE_CCM, nonce=nonce, mac_len=mic_len)
    if aad:
        cipher.update(aad)
    ciphertext, mic = cipher.encrypt_and_digest(plaintext)
    return ciphertext, mic


def aes_ccm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, mic: bytes, aad: bytes) -> bytes:
    """AES-CCM decrypt + verify. Raises ValueError if the MIC doesn't match."""
    cipher = AES.new(key, AES.MODE_CCM, nonce=nonce, mac_len=len(mic))
    if aad:
        cipher.update(aad)
    return cipher.decrypt_and_verify(ciphertext, mic)


# ---------------------------------------------------------------------------
# Self-test against the official RFC 4493 AES-CMAC test vectors (these are
# NOT mesh-specific -- they're the universal, independently-published
# reference vectors for AES-128-CMAC itself, cross-checked against multiple
# independent open-source implementations). This verifies the underlying
# CMAC primitive is correct. It does NOT independently verify the s1/k1/k2/
# k3/k4 formula construction on top of it (those are implemented directly
# from Mesh Profile Specification v1.0.1 Section 3.8, but not verified here
# against an official mesh test vector -- I was not confident enough in a
# from-memory mesh-specific vector to hardcode it without a citation).
#
# The real end-to-end validation for this integration is: does the light
# actually respond correctly. If it doesn't, start debugging here.
# ---------------------------------------------------------------------------

def _self_test() -> None:
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")

    # RFC 4493 Example 1: empty message.
    result = aes_cmac(key, b"")
    expected = bytes.fromhex("bb1d6929e95937287fa37d129b756746"[:32])
    if result != expected:
        raise AssertionError(
            f"aes_cmac() self-test (empty msg) failed: got {result.hex()}, expected {expected.hex()}"
        )

    # RFC 4493 Example 2: 16-byte message (exactly one block).
    msg = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"[:32])
    result = aes_cmac(key, msg)
    expected = bytes.fromhex("070a16b46b4d4144f79bdd9dd04a287c"[:32])
    if result != expected:
        raise AssertionError(
            f"aes_cmac() self-test (16-byte msg) failed: got {result.hex()}, expected {expected.hex()}"
        )


_self_test()
