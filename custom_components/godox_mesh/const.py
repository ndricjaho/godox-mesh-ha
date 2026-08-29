"""Constants for the Godox Mesh Light integration."""

DOMAIN = "godox_mesh"

CONF_MAC_ADDRESS = "mac_address"
CONF_UNICAST_ADDRESS = "unicast_address"
CONF_NET_KEY = "net_key"
CONF_APP_KEY = "app_key"
CONF_PROVISIONER_ADDRESS = "provisioner_address"

DEFAULT_PROVISIONER_ADDRESS = 0x0001

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_seq"
