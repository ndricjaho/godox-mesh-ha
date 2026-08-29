"""Godox vendor-model command builders.

Reverse-engineered from the Godox Light Android app (decompiled
com.godox.agm.GodoxCommandApi / CRC8Util) and verified live against a
real Godox TL120 (on/off and HSI color both confirmed working).

Vendor model: company ID 0x0211 (Telink Semiconductor), model 0x0000.
All commands are sent on outer vendor opcode 0xF0 (unacknowledged), with
an inner Godox "sub-command" byte identifying what kind of command it is.

There are TWO inner wire formats, both CRC8-checksummed with the same
table, but structured differently:

  "V2" format (fixed 8 bytes) -- used by on/off, HSI, CCT, RGBW, and a
  few others:
      [subcmd, data[0..4] (5 bytes), trailing_byte, CRC8]

  "V3" format (variable length) -- used by most of the lighting effects
  (fire, candle, police car, TV, music, SOS, etc.):
      [subcmd, total_length, data[0..N-1] (N bytes), CRC8]
      where total_length = N + 3 (the packet's own total byte count)

Confidence levels, honestly:
  - build_onoff() / build_hsi(): CONFIRMED. Verified live, byte-for-byte,
    against a real TL120.
  - build_cct(): EXPERIMENTAL. The wire *structure* (V2 format, subcmd
    0xF0) and the brightness split are confirmed from the decompiled
    code. The exact encoding of color temperature and the "GM" (green/
    magenta tint) fields is NOT fully confirmed -- a single byte can't
    hold a raw Kelvin value like 5600, so the real app is clearly
    scaling it somehow, and that scaling wasn't pinned down from static
    analysis alone. Test cautiously; start from a known-safe/neutral
    value.
  - Lighting effects (fire, candle, SOS, police car, TV, music, etc.):
    NOT IMPLEMENTED. The V3 wire *framing* above is fully confirmed from
    the decompiled sendAgreementDataV3(), but the per-effect payload
    layout (what each data byte means for a given effect) hasn't been
    traced. See PROTOCOL.md for the full sub-command reference table --
    tracing any one of these the same way build_cct() was traced (find
    the method in GodoxCommandApi.smali, find its real UI caller, work
    out which register maps to which real-world parameter) should reveal
    it. Contributions welcome.
"""
from __future__ import annotations

COMPANY_ID_TELINK = 0x0211
VENDOR_OPCODE_BYTE = 0xF0

SUBCMD_ONOFF = 0xFE
SUBCMD_HSI = 0xF1
SUBCMD_CCT = 0xF0
SUBCMD_RGBW = 0xF2
SUBCMD_GENERIC_FX = 0xF3
SUBCMD_CARD = 0xF4
SUBCMD_ELECTRIC_FAN = 0xF5

# CRC8 lookup table extracted verbatim from com.godox.agm.CRC8Util
# (256-entry table-driven CRC8, see custom_components/godox_mesh/mesh/crc8_table.py
# for how it was pulled directly out of the decompiled app).
from .crc8_table import crc8  # noqa: E402


def _build_v2_packet(subcmd: int, data5: bytes, trailing_byte: int) -> bytes:
    """Build a fixed-length 8-byte Godox inner command packet ("V2" format).

    Layout: [subcmd, data5[0], data5[1], data5[2], data5[3], data5[4],
             trailing_byte, CRC8-of-preceding-7-bytes]
    """
    assert len(data5) == 5
    payload = bytes([subcmd]) + data5 + bytes([trailing_byte & 0xFF])
    return payload + bytes([crc8(payload)])


def build_v3_packet(subcmd: int, data: bytes) -> bytes:
    """Build a variable-length Godox inner command packet ("V3" format).

    Layout: [subcmd, total_length, data[0..N-1], CRC8], where
    total_length = len(data) + 3 (the whole packet's own byte count).

    This framing is fully confirmed from the decompiled
    sendAgreementDataV3(). It's exposed here (rather than kept private)
    for anyone tracing one of the lighting-effect commands -- see
    PROTOCOL.md for the sub-command byte for each effect.
    """
    total_length = len(data) + 3
    body = bytes([subcmd, total_length & 0xFF]) + data
    return body + bytes([crc8(body)])


def build_onoff(turn_on: bool) -> bytes:
    """Build the on/off command payload. CONFIRMED (verified live).

    NB: the on/off bit is inverted in the wire protocol -- 0x00 means ON,
    0x01 means OFF (confirmed live against a real light).
    """
    onoff_byte = 0x00 if turn_on else 0x01
    data5 = bytes([onoff_byte, 0xFF, 0xFF, 0xFF, 0xFF])
    return _build_v2_packet(SUBCMD_ONOFF, data5, trailing_byte=0xFF)


def build_hsi(hue: int, saturation: int, brightness_pct: float) -> bytes:
    """Build an HSI (Hue/Saturation/Intensity) color command. CONFIRMED
    (verified live).

    hue: 0-360 (degrees)
    saturation: 0-100
    brightness_pct: 0.0-100.0 (Godox's app splits this into an integer
        part and a one-digit decimal part, e.g. 55.3% is sent as
        intensity_int=55, intensity_point=3)
    """
    if not (0 <= hue <= 360):
        raise ValueError("hue must be 0-360")
    if not (0 <= saturation <= 100):
        raise ValueError("saturation must be 0-100")
    if not (0.0 <= brightness_pct <= 100.0):
        raise ValueError("brightness_pct must be 0-100")

    intensity_int = int(brightness_pct)
    intensity_point = round((brightness_pct - intensity_int) * 10) & 0x0F

    hue_low = hue & 0xFF
    hue_high = (hue >> 8) & 0xFF
    mode_hsi = 0x02

    data5 = bytes([intensity_int & 0xFF, hue_low, hue_high, saturation & 0xFF, mode_hsi])
    return _build_v2_packet(SUBCMD_HSI, data5, trailing_byte=intensity_point)


def build_cct(color_temp_kelvin: int, brightness_pct: float, gm_tint: int = 0) -> bytes:
    """Build a CCT (color temperature) command. EXPERIMENTAL -- see the
    module docstring. The brightness split and overall structure are
    confirmed; the temperature/tint byte encoding is not.

    As a starting guess (NOT confirmed), this assumes the app sends
    (kelvin - 2700) // 100 as a single byte, giving a 0-38 range across
    the TL120's rated 2700K-6500K -- a common encoding pattern for this
    kind of single-byte field, but genuinely unverified. If it doesn't
    produce the expected color temperature live, that's the first thing
    to re-derive.

    gm_tint: green/magenta tint offset. Passed through mostly as-is;
    valid range and sign convention are unconfirmed. Leave at 0 unless
    you're actively trying to figure this field out.
    """
    if not (2700 <= color_temp_kelvin <= 6500):
        raise ValueError("color_temp_kelvin must be 2700-6500 (TL120's rated range)")
    if not (0.0 <= brightness_pct <= 100.0):
        raise ValueError("brightness_pct must be 0-100")

    intensity_int = int(brightness_pct)
    intensity_point = round((brightness_pct - intensity_int) * 10) & 0x0F

    temp_byte = (color_temp_kelvin - 2700) // 100  # UNVERIFIED encoding, see docstring
    gm_byte = gm_tint & 0xFF
    mode_byte = 0x00  # UNVERIFIED -- clamped to 0-3 by the app, meaning unknown

    data5 = bytes([intensity_int & 0xFF, temp_byte & 0xFF, gm_byte, mode_byte, gm_byte])
    return _build_v2_packet(SUBCMD_CCT, data5, trailing_byte=intensity_point)

