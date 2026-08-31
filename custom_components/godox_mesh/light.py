"""Godox Mesh Light entity.

State is optimistic (assumed_state = True): these lights don't send a
usable status reply over the vendor model we're using, so rather than
pretend to poll a real status, we track what we last told the light to
do and report that. If a command silently fails to reach the light
(e.g. it's out of range), Home Assistant's state will drift from
reality until the next successful command -- this is a real limitation
worth knowing about, not hidden behind a fake "confirmed" state.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAC_ADDRESS, CONF_MODEL, DEFAULT_MODEL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    stored = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GodoxMeshLightEntity(entry, stored["light"], stored["persist_seq"])])


class GodoxMeshLightEntity(LightEntity):
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS}

    def __init__(self, entry: ConfigEntry, light, persist_seq) -> None:
        self._entry = entry
        self._light = light
        self._persist_seq = persist_seq

        self._attr_unique_id = entry.unique_id
        self._attr_name = entry.title
        self._attr_is_on = False
        self._attr_hs_color = (0.0, 0.0)
        self._attr_brightness = 255

        mac = entry.data[CONF_MAC_ADDRESS]
        model = entry.data.get(CONF_MODEL, DEFAULT_MODEL)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, mac)},
            "connections": {(dr.CONNECTION_BLUETOOTH, mac)},
            "name": entry.title,
            "manufacturer": "Godox",
            "model": f"{model} (Telink Mesh, vendor opcode 0xF0)",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        hs_color = kwargs.get("hs_color", self._attr_hs_color)
        brightness = kwargs.get("brightness", self._attr_brightness)
        brightness_pct = (brightness / 255) * 100

        if "hs_color" in kwargs or "brightness" in kwargs:
            hue, sat = hs_color
            await self._light.set_hsi(int(round(hue)), int(round(sat)), brightness_pct)
            self._attr_hs_color = hs_color
            self._attr_brightness = brightness
        else:
            await self._light.turn_on()

        self._attr_is_on = True
        await self._persist_seq()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._light.turn_off()
        self._attr_is_on = False
        await self._persist_seq()
        self.async_write_ha_state()
