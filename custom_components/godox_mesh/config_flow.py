"""Config flow for Godox Mesh Light.

Every field here comes from the user's own nRF Mesh provisioning of
their own light -- nothing is hardcoded. See the README for how to
obtain each of these values.
"""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_APP_KEY,
    CONF_MAC_ADDRESS,
    CONF_NET_KEY,
    CONF_PROVISIONER_ADDRESS,
    CONF_UNICAST_ADDRESS,
    DEFAULT_PROVISIONER_ADDRESS,
    DOMAIN,
)

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HEX_KEY_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    """Return a dict of field -> error code for anything invalid."""
    errors: dict[str, str] = {}

    if not MAC_RE.match(user_input[CONF_MAC_ADDRESS].strip()):
        errors[CONF_MAC_ADDRESS] = "invalid_mac"

    if not HEX_KEY_RE.match(user_input[CONF_NET_KEY].strip()):
        errors[CONF_NET_KEY] = "invalid_key"

    if not HEX_KEY_RE.match(user_input[CONF_APP_KEY].strip()):
        errors[CONF_APP_KEY] = "invalid_key"

    for field in (CONF_UNICAST_ADDRESS, CONF_PROVISIONER_ADDRESS):
        raw = str(user_input[field]).strip()
        try:
            value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 16)
            if not (0 < value < 0x8000):
                raise ValueError
        except ValueError:
            errors[field] = "invalid_address"

    return errors


class GodoxMeshConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for one Godox mesh light."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                unicast = int(user_input[CONF_UNICAST_ADDRESS], 16)
                provisioner = int(user_input[CONF_PROVISIONER_ADDRESS], 16)

                await self.async_set_unique_id(user_input[CONF_MAC_ADDRESS].upper())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get("name") or f"Godox Light ({user_input[CONF_MAC_ADDRESS]})",
                    data={
                        CONF_MAC_ADDRESS: user_input[CONF_MAC_ADDRESS].upper(),
                        CONF_UNICAST_ADDRESS: unicast,
                        CONF_NET_KEY: user_input[CONF_NET_KEY].upper(),
                        CONF_APP_KEY: user_input[CONF_APP_KEY].upper(),
                        CONF_PROVISIONER_ADDRESS: provisioner,
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional("name"): str,
                vol.Required(CONF_MAC_ADDRESS): str,
                vol.Required(CONF_UNICAST_ADDRESS, default="0x0002"): str,
                vol.Required(CONF_PROVISIONER_ADDRESS, default="0x0001"): str,
                vol.Required(CONF_NET_KEY): str,
                vol.Required(CONF_APP_KEY): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
