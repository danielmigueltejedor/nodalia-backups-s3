"""Nodalia Wasabi backup integration for Home Assistant."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import functools
import logging
from typing import Any, TypeVar, cast

from botocore.exceptions import (
    ClientError,
    ConnectionError as BotoConnectionError,
    ParamValidationError,
)
from botocore.session import Session

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from .const import (
    AGENT_LISTENER_KEY,
    CONF_ACCESS_KEY_ID,
    CONF_ADDITIONAL_HOUSE,
    CONF_BUCKET,
    CONF_INSTALLATION_NAME,
    CONF_PREFIX,
    CONF_REGION,
    CONF_ROOT_PATH,
    CONF_SECRET_ACCESS_KEY,
    DEFAULT_ROOT_PATH,
    DOMAIN,
    STORAGE_DIR,
)
from .utils import (
    append_storage_subpath,
    build_entry_title,
    build_storage_prefix,
    build_wasabi_endpoint,
    create_s3_client_config,
)

NodaliaBackupsEntry = ConfigEntry["WasabiStorageGateway"]
_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class _ExecutorStreamBody:
    """Expose a sync streaming body through async helpers."""

    def __init__(self, gateway: "WasabiStorageGateway", body: Any) -> None:
        self._gateway = gateway
        self._body = body

    async def read(self, amt: int | None = None) -> bytes:
        """Read bytes from the streaming body in the executor."""
        if amt is None:
            return await self._gateway._async_call(self._body.read)
        return await self._gateway._async_call(self._body.read, amt)

    async def iter_chunks(self, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Yield body chunks without blocking the event loop."""
        try:
            while chunk := await self.read(chunk_size):
                yield chunk
        finally:
            await self.close()

    async def close(self) -> None:
        """Close the underlying streaming body."""
        close = getattr(self._body, "close", None)
        if callable(close):
            await self._gateway._async_call(close)


class WasabiStorageGateway:
    """Async wrapper around a blocking botocore S3 client."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        key_id: str,
        secret: str,
        region: str,
        bucket: str,
        prefix: str,
    ) -> None:
        self._hass = hass
        self._bucket = bucket
        self._region = region
        self._endpoint = build_wasabi_endpoint(region)
        self._prefix = prefix.strip("/")
        self._client: Any = None
        self._key_id = key_id
        self._secret = secret

    async def _async_call(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run a blocking call in Home Assistant's executor."""
        return await self._hass.async_add_executor_job(
            functools.partial(func, *args, **kwargs)
        )

    def _create_client(self) -> Any:
        """Create a blocking botocore client."""
        session = Session()
        return session.create_client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._key_id,
            aws_secret_access_key=self._secret,
            region_name=self._region,
            config=create_s3_client_config(),
        )

    async def async_start(self) -> None:
        """Open the Wasabi client and verify listing access for this prefix."""
        if self._client is not None:
            return

        self._client = await self._async_call(self._create_client)
        try:
            await self.list_objects_v2(
                Bucket=self._bucket,
                Prefix=f"{self._prefix}/{STORAGE_DIR}/",
                MaxKeys=1,
            )
        except Exception:
            await self.async_stop()
            raise

    async def async_stop(self) -> None:
        """Close the Wasabi client."""
        if self._client is None:
            return

        close = getattr(self._client, "close", None)
        if callable(close):
            await self._async_call(close)
        self._client = None

    async def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.head_bucket, **kwargs)

    async def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.list_objects_v2, **kwargs)

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        response = dict(await self._async_call(self._client.get_object, **kwargs))
        response["Body"] = _ExecutorStreamBody(self, response["Body"])
        return response

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.put_object, **kwargs)

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.delete_object, **kwargs)

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.create_multipart_upload, **kwargs)

    async def upload_part(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.upload_part, **kwargs)

    async def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(
            self._client.complete_multipart_upload, **kwargs
        )

    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        return await self._async_call(self._client.abort_multipart_upload, **kwargs)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate existing entries to the latest schema."""
    if entry.version > 1:
        return False

    if entry.version == 1 and entry.minor_version < 2:
        new_data = {**entry.data}
        new_data.setdefault(CONF_ADDITIONAL_HOUSE, "")

        try:
            base_prefix = build_storage_prefix(
                new_data.get(CONF_ROOT_PATH, DEFAULT_ROOT_PATH),
                new_data[CONF_INSTALLATION_NAME],
            )
            new_data[CONF_PREFIX] = append_storage_subpath(
                base_prefix,
                new_data.get(CONF_ADDITIONAL_HOUSE, ""),
            )
        except (KeyError, ValueError):
            _LOGGER.exception("Could not migrate entry %s", entry.entry_id)
            return False

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            title=build_entry_title(
                new_data[CONF_INSTALLATION_NAME],
                new_data.get(CONF_ADDITIONAL_HOUSE, ""),
            ),
            version=1,
            minor_version=2,
        )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: NodaliaBackupsEntry
) -> bool:
    """Initialise a config entry."""
    cfg = cast(dict[str, Any], entry.data)

    gateway = WasabiStorageGateway(
        hass=hass,
        key_id=cfg[CONF_ACCESS_KEY_ID],
        secret=cfg[CONF_SECRET_ACCESS_KEY],
        region=cfg[CONF_REGION],
        bucket=cfg[CONF_BUCKET],
        prefix=cfg[CONF_PREFIX],
    )

    try:
        await gateway.async_start()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_credentials",
            ) from exc
        if error_code in {"NoSuchBucket", "404"}:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="bucket_not_found",
            ) from exc
        raise
    except ParamValidationError as exc:
        if "Invalid bucket name" in str(exc):
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="invalid_bucket_name",
            ) from exc
        raise
    except ValueError as exc:
        if str(exc) == "invalid_region":
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="invalid_region",
            ) from exc
        raise
    except BotoConnectionError as exc:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from exc

    entry.runtime_data = gateway

    def _propagate_state_change() -> None:
        for callback in hass.data.get(AGENT_LISTENER_KEY, []):
            callback()

    entry.async_on_unload(entry.async_on_state_change(_propagate_state_change))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NodaliaBackupsEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_stop()
    return True
