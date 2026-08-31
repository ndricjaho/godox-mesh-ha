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
from homeassistant.helpers import selector

from .const import (
    CONF_APP_KEY,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    CONF_NET_KEY,
    CONF_PROVISIONER_ADDRESS,
    CONF_UNICAST_ADDRESS,
    DEFAULT_MODEL,
    DEFAULT_PROVISIONER_ADDRESS,
    DOMAIN,
    KNOWN_MODELS,
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


def _schema() -> vol.Schema:
    """Schema shared by the initial add flow and the reconfigure flow.

    Reconfigure pre-fills this via add_suggested_values_to_schema() rather
    than per-call defaults, so the field defaults here only matter for the
    initial add flow.
    """
    return vol.Schema(
        {
            vol.Optional("name"): str,
            vol.Required(CONF_MAC_ADDRESS): str,
            vol.Required(CONF_UNICAST_ADDRESS, default="0x0002"): str,
            vol.Required(CONF_PROVISIONER_ADDRESS, default="0x0001"): str,
            vol.Required(CONF_NET_KEY): str,
            vol.Required(CONF_APP_KEY): str,
            vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=KNOWN_MODELS,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _entry_data(user_input: dict[str, Any], mac: str) -> dict[str, Any]:
    return {
        CONF_MAC_ADDRESS: mac,
        CONF_UNICAST_ADDRESS: int(user_input[CONF_UNICAST_ADDRESS], 16),
        CONF_NET_KEY: user_input[CONF_NET_KEY].upper(),
        CONF_APP_KEY: user_input[CONF_APP_KEY].upper(),
        CONF_PROVISIONER_ADDRESS: int(user_input[CONF_PROVISIONER_ADDRESS], 16),
        CONF_MODEL: (user_input.get(CONF_MODEL) or DEFAULT_MODEL).strip(),
    }


class GodoxMeshConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for one Godox mesh light."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                mac = user_input[CONF_MAC_ADDRESS].upper()

                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get("name") or f"Godox Light ({mac})",
                    data=_entry_data(user_input, mac),
                )

        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Let the user review and correct MAC/keys/addresses/model for an
        already-added light, without deleting and re-adding it."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(user_input)
            mac = user_input[CONF_MAC_ADDRESS].upper()

            if not errors:
                for other in self._async_current_entries():
                    if other.entry_id != reconfigure_entry.entry_id and other.unique_id == mac:
                        errors[CONF_MAC_ADDRESS] = "duplicate_mac"
                        break

            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    unique_id=mac,
                    title=user_input.get("name") or f"Godox Light ({mac})",
                    data=_entry_data(user_input, mac),
                )

        suggested = {
            "name": reconfigure_entry.title,
            CONF_MAC_ADDRESS: reconfigure_entry.data[CONF_MAC_ADDRESS],
            CONF_UNICAST_ADDRESS: f"0x{reconfigure_entry.data[CONF_UNICAST_ADDRESS]:04X}",
            CONF_PROVISIONER_ADDRESS: f"0x{reconfigure_entry.data[CONF_PROVISIONER_ADDRESS]:04X}",
            CONF_NET_KEY: reconfigure_entry.data[CONF_NET_KEY],
            CONF_APP_KEY: reconfigure_entry.data[CONF_APP_KEY],
            CONF_MODEL: reconfigure_entry.data.get(CONF_MODEL, DEFAULT_MODEL),
        }
        schema = self.add_suggested_values_to_schema(_schema(), suggested)
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
