"""Constants for the Nodalia Wasabi backup integration."""

from collections.abc import Callable
from typing import Final

from homeassistant.util.hass_dict import HassKey

DOMAIN: Final = "nodalia_backups_s3"

CONF_ACCESS_KEY_ID: Final = "access_key_id"
CONF_SECRET_ACCESS_KEY: Final = "secret_access_key"
CONF_BUCKET: Final = "bucket"
CONF_REGION: Final = "region"
CONF_INSTALLATION_NAME: Final = "installation_name"
CONF_ADDITIONAL_HOUSE: Final = "additional_house"
CONF_ROOT_PATH: Final = "root_path"
CONF_PREFIX: Final = "prefix"

DEFAULT_BUCKET: Final = "nodalia-backups"
DEFAULT_REGION: Final = "eu-west-2"
DEFAULT_ROOT_PATH: Final = "homeassistant"
STORAGE_DIR: Final = "backups"
SERVER_SIDE_ENCRYPTION: Final = "AES256"
WASABI_ENDPOINT_TEMPLATE: Final = "https://s3.{region}.wasabisys.com"
PROBE_OBJECT_NAME: Final = ".nodalia-connection-check"

AGENT_LISTENER_KEY: HassKey[list[Callable[[], None]]] = HassKey(
    f"{DOMAIN}.agent_listeners"
)
