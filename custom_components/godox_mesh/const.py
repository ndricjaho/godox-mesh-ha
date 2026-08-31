"""Constants for the Godox Mesh Light integration."""

DOMAIN = "godox_mesh"

CONF_MAC_ADDRESS = "mac_address"
CONF_UNICAST_ADDRESS = "unicast_address"
CONF_NET_KEY = "net_key"
CONF_APP_KEY = "app_key"
CONF_PROVISIONER_ADDRESS = "provisioner_address"
CONF_MODEL = "model"

DEFAULT_PROVISIONER_ADDRESS = 0x0001
DEFAULT_MODEL = "TL120"
KNOWN_MODELS = ["TL120", "TL60", "TL30"]

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_seq"
