"""Tests for the self-contained mesh/ subpackage.

Run with: python -m pytest tests/
(No Home Assistant installation required -- these only exercise
custom_components/godox_mesh/mesh/, which has no HA dependency.)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "godox_mesh"))

from mesh import crypto, godox_commands, network, proxy
from mesh.crc8_table import crc8
from mesh.seq import SequenceCounter


def test_cmac_rfc4493_vectors():
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    assert crypto.aes_cmac(key, b"").hex() == "bb1d6929e95937287fa37d129b756746"[:32]
    msg = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"[:32])
    assert crypto.aes_cmac(key, msg).hex() == "070a16b46b4d4144f79bdd9dd04a287c"[:32]


def test_crc8_matches_live_confirmed_payload():
    # This exact payload was sent to a real Godox TL120 and confirmed to
    # turn it off.
    payload = godox_commands.build_onoff(turn_on=False)
    assert payload.hex().upper() == "FE01FFFFFFFFFF48"


def test_crc8_matches_live_confirmed_on_payload():
    payload = godox_commands.build_onoff(turn_on=True)
    assert payload.hex().upper() == "FE00FFFFFFFFFF7F"


def test_crc8_matches_live_confirmed_hsi_payload():
    # Green, full saturation, 50% brightness -- confirmed live.
    payload = godox_commands.build_hsi(hue=120, saturation=100, brightness_pct=50.0)
    assert payload.hex().upper() == "F132780064020003"


def test_cct_builder_produces_right_shape_and_valid_crc():
    # EXPERIMENTAL -- not verified live (see PROTOCOL.md), this only checks
    # internal consistency (right length, right subcmd, CRC actually
    # matches its own payload), not that the light interprets it correctly.
    payload = godox_commands.build_cct(color_temp_kelvin=5600, brightness_pct=80.0)
    assert len(payload) == 8
    assert payload[0] == godox_commands.SUBCMD_CCT
    assert crc8(payload[:7]) == payload[7]


def test_cct_rejects_out_of_range_temperature():
    import pytest

    with pytest.raises(ValueError):
        godox_commands.build_cct(color_temp_kelvin=2000, brightness_pct=50)  # below TL120's rated range
    with pytest.raises(ValueError):
        godox_commands.build_cct(color_temp_kelvin=7000, brightness_pct=50)  # above TL120's rated range


def test_v3_packet_framing():
    data = bytes([0x01, 0x02, 0x03])
    packet = godox_commands.build_v3_packet(subcmd=0xF3, data=data)
    assert packet[0] == 0xF3
    assert packet[1] == len(data) + 3  # self-referential total length
    assert packet[2:5] == data
    assert crc8(packet[:-1]) == packet[-1]


def test_hsi_rejects_out_of_range():
    import pytest

    with pytest.raises(ValueError):
        godox_commands.build_hsi(hue=400, saturation=50, brightness_pct=50)
    with pytest.raises(ValueError):
        godox_commands.build_hsi(hue=100, saturation=150, brightness_pct=50)


def test_k2_output_shapes():
    nid, enc_key, priv_key = crypto.k2(bytes(16), b"\x00")
    assert 0 <= nid <= 0x7F
    assert len(enc_key) == 16
    assert len(priv_key) == 16


def test_k4_output_is_6_bits():
    aid = crypto.k4(bytes(16))
    assert 0 <= aid <= 0x3F


def test_network_pdu_seq_changes_ciphertext():
    net_key = bytes.fromhex("00" * 16)
    app_key = bytes.fromhex("11" * 16)
    payload = godox_commands.build_onoff(turn_on=True)

    pdu1 = network.build_message(
        net_key=net_key, app_key=app_key, src=1, dst=2, seq=1, iv_index=0,
        vendor_opcode_byte=godox_commands.VENDOR_OPCODE_BYTE,
        company_id=godox_commands.COMPANY_ID_TELINK, params=payload,
    )
    pdu2 = network.build_message(
        net_key=net_key, app_key=app_key, src=1, dst=2, seq=2, iv_index=0,
        vendor_opcode_byte=godox_commands.VENDOR_OPCODE_BYTE,
        company_id=godox_commands.COMPANY_ID_TELINK, params=payload,
    )
    assert pdu1 != pdu2


def test_network_pdu_deterministic_for_same_inputs():
    net_key = bytes.fromhex("00" * 16)
    app_key = bytes.fromhex("11" * 16)
    payload = godox_commands.build_onoff(turn_on=True)

    args = dict(
        net_key=net_key, app_key=app_key, src=1, dst=2, seq=1, iv_index=0,
        vendor_opcode_byte=godox_commands.VENDOR_OPCODE_BYTE,
        company_id=godox_commands.COMPANY_ID_TELINK, params=payload,
    )
    assert network.build_message(**args) == network.build_message(**args)


def test_vendor_opcode_range_enforced():
    import pytest

    with pytest.raises(ValueError):
        network.build_access_payload(0x50, 0x0211, b"\x00")  # not in 0xC0-0xFF


def test_sequence_counter_persists_and_advances():
    counter = SequenceCounter(start=5)
    assert counter.next() == 5
    assert counter.next() == 6
    saved = counter.to_dict()
    restored = SequenceCounter.from_dict(saved)
    assert restored.value == 7
    assert restored.next() == 7


def test_sequence_counter_rejects_reuse_via_max():
    counter = SequenceCounter(start=0xFFFFFF)
    try:
        counter.next()
        assert False, "should have raised"
    except RuntimeError:
        pass


def test_proxy_pdu_framing_small_message_is_unsegmented():
    frames = proxy.frame_network_pdu(b"\x01\x02\x03", att_mtu=23)
    assert len(frames) == 1
    assert frames[0][0] >> 6 == proxy.SAR_COMPLETE


def test_proxy_pdu_framing_large_message_is_segmented():
    big = bytes(range(100)) * 2  # 200 bytes, definitely needs segmentation
    frames = proxy.frame_network_pdu(big, att_mtu=23)
    assert len(frames) > 1
    assert frames[0][0] >> 6 == proxy.SAR_FIRST
    assert frames[-1][0] >> 6 == proxy.SAR_LAST
    for mid in frames[1:-1]:
        assert mid[0] >> 6 == proxy.SAR_CONTINUATION
