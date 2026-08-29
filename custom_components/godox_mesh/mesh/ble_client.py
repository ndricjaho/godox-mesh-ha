"""BLE transport: connects to a Godox light's Mesh Proxy GATT service and
sends already-encrypted Network PDUs.

Standard Bluetooth Mesh Proxy Service/Characteristic UUIDs (Mesh Profile
Spec Section 6.3): these are the same on every Mesh device regardless of
vendor, so no hardcoded GATT handles are used (handles can differ per
device/firmware; UUIDs don't).

Connections go through bleak-retry-connector's establish_connection()
rather than a raw BleakClient(address). This matters specifically under
Home Assistant: HA's Bluetooth integration centrally manages the
adapter(s), connection slots, and device discovery cache, and expects
integrations to hand it a BLEDevice it already knows about (obtained via
homeassistant.components.bluetooth.async_ble_device_from_address())
rather than connecting to a bare MAC address string directly. Bypassing
that causes exactly the "BleakClient.connect() called without
bleak-retry-connector" warning HA logs -- and in practice, unreliable or
outright failing connections once anything else is contending for the
adapter.

This module itself stays HA-independent (no `homeassistant` imports) --
callers (see the integration's __init__.py) are expected to supply a
`ble_device_provider` callback that returns a fresh `bleak.BLEDevice`,
however they source it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from . import network, proxy
from .seq import SequenceCounter

_LOGGER = logging.getLogger(__name__)

MESH_PROXY_SERVICE_UUID = "00001828-0000-1000-8000-00805f9b34fb"
MESH_PROXY_DATA_IN_UUID = "00002add-0000-1000-8000-00805f9b34fb"
MESH_PROXY_DATA_OUT_UUID = "00002ade-0000-1000-8000-00805f9b34fb"

DEFAULT_ATT_MTU = 23  # conservative default; bleak will tell us the real
                       # negotiated value once connected, if it's larger.


class GodoxMeshLight:
    """One physical light, addressed over its own BLE connection.

    Connect-per-command rather than holding a persistent connection: these
    lights only support a small number of simultaneous GATT connections
    (shared with the Godox app / other controllers), and connect latency
    for a single small command is a fraction of a second, which is fine
    for a light switch.
    """

    def __init__(
        self,
        mac_address: str,
        unicast_address: int,
        net_key: bytes,
        app_key: bytes,
        provisioner_address: int,
        seq_counter: SequenceCounter,
        ble_device_provider: Callable[[], BLEDevice],
        iv_index: int = 0,
    ) -> None:
        self.mac_address = mac_address
        self.unicast_address = unicast_address
        self.net_key = net_key
        self.app_key = app_key
        self.provisioner_address = provisioner_address
        self.seq_counter = seq_counter
        self.iv_index = iv_index
        self._ble_device_provider = ble_device_provider
        # Serializes connection attempts to THIS device from our own code.
        # BlueZ raises org.bluez.Error.InProgress if a second connect is
        # issued to the same address while one is still underway (e.g. two
        # commands fired back-to-back before the first finished its
        # retries) -- this lock makes that structurally impossible rather
        # than relying on the caller never doing it.
        self._connect_lock = asyncio.Lock()

    async def _send_params(self, params: bytes) -> None:
        from .godox_commands import VENDOR_OPCODE_BYTE, COMPANY_ID_TELINK

        seq = self.seq_counter.next()
        pdu = network.build_message(
            net_key=self.net_key,
            app_key=self.app_key,
            src=self.provisioner_address,
            dst=self.unicast_address,
            seq=seq,
            iv_index=self.iv_index,
            vendor_opcode_byte=VENDOR_OPCODE_BYTE,
            company_id=COMPANY_ID_TELINK,
            params=params,
        )

        async with self._connect_lock:
            device = self._ble_device_provider()
            if device is None:
                raise RuntimeError(
                    f"{self.mac_address} is not currently visible to Home Assistant's "
                    "Bluetooth integration -- is the light powered on and in range of "
                    "an adapter or Bluetooth proxy?"
                )

            client: BleakClient = await establish_connection(
                BleakClient,
                device,
                self.mac_address,
                ble_device_callback=self._ble_device_provider,
            )
            try:
                att_mtu = getattr(client, "mtu_size", DEFAULT_ATT_MTU) or DEFAULT_ATT_MTU
                frames = proxy.frame_network_pdu(pdu, att_mtu)
                data_in_char = client.services.get_characteristic(MESH_PROXY_DATA_IN_UUID)
                if data_in_char is None:
                    raise RuntimeError(
                        f"{self.mac_address} doesn't expose the Mesh Proxy Data In "
                        "characteristic -- is this really a provisioned mesh light?"
                    )
                for frame in frames:
                    await client.write_gatt_char(data_in_char, frame, response=False)
                    _LOGGER.debug("Sent proxy frame to %s: %s", self.mac_address, frame.hex())
            finally:
                await client.disconnect()

    async def turn_on(self) -> None:
        from .godox_commands import build_onoff

        await self._send_params(build_onoff(turn_on=True))

    async def turn_off(self) -> None:
        from .godox_commands import build_onoff

        await self._send_params(build_onoff(turn_on=False))

    async def set_hsi(self, hue: int, saturation: int, brightness_pct: float) -> None:
        from .godox_commands import build_hsi

        await self._send_params(build_hsi(hue, saturation, brightness_pct))

    async def set_cct(self, color_temp_kelvin: int, brightness_pct: float, gm_tint: int = 0) -> None:
        """EXPERIMENTAL -- see godox_commands.build_cct()'s docstring and
        PROTOCOL.md before relying on this. Deliberately not wired into the
        light entity's UI (light.py only exposes the confirmed HS color
        mode); available here for anyone testing/tracing the real encoding
        via Developer Tools -> Services or their own script."""
        from .godox_commands import build_cct

        await self._send_params(build_cct(color_temp_kelvin, brightness_pct, gm_tint))

