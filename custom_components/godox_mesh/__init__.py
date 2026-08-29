"""The Godox Mesh Light integration."""
from __future__ import annotations

import hashlib
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_APP_KEY,
    CONF_MAC_ADDRESS,
    CONF_NET_KEY,
    CONF_PROVISIONER_ADDRESS,
    CONF_UNICAST_ADDRESS,
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .mesh.ble_client import GodoxMeshLight
from .mesh.seq import SequenceCounter

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light"]


def _storage_key_for_network(net_key_hex: str) -> str:
    """Derive a storage filename from the NetKey without writing the raw
    key itself into a filename on disk."""
    digest = hashlib.sha256(bytes.fromhex(net_key_hex)).hexdigest()[:16]
    return f"{STORAGE_KEY_PREFIX}_{digest}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data

    store: Store = Store(hass, STORAGE_VERSION, _storage_key_for_network(data[CONF_NET_KEY]))
    stored = await store.async_load()
    seq_counter = SequenceCounter.from_dict(stored or {})

    async def _persist_seq() -> None:
        await store.async_save(seq_counter.to_dict())

    mac_address = data[CONF_MAC_ADDRESS]

    def _get_ble_device():
        # Pulls from Home Assistant's own Bluetooth device cache -- this is
        # what makes the connection play nicely with HA's central adapter/
        # connection-slot management (including Bluetooth proxies), instead
        # of bleak connecting to a bare address on its own.
        device = bluetooth.async_ble_device_from_address(hass, mac_address, connectable=True)
        if device is None:
            _LOGGER.warning(
                "%s not currently visible to Home Assistant's Bluetooth integration "
                "(not powered on / out of range / no adapter or proxy covering it)",
                mac_address,
            )
        return device

    light = GodoxMeshLight(
        mac_address=mac_address,
        unicast_address=data[CONF_UNICAST_ADDRESS],
        net_key=bytes.fromhex(data[CONF_NET_KEY]),
        app_key=bytes.fromhex(data[CONF_APP_KEY]),
        provisioner_address=data[CONF_PROVISIONER_ADDRESS],
        seq_counter=seq_counter,
        ble_device_provider=_get_ble_device,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "light": light,
        "persist_seq": _persist_seq,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
