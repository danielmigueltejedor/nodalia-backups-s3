"""Config flow for the Nodalia Wasabi backup integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import functools
from typing import Any

from aiobotocore.session import AioSession
from botocore.exceptions import (
    ClientError,
    ConnectionError as BotoConnectionError,
    ParamValidationError,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ACCESS_KEY_ID,
    CONF_BUCKET,
    CONF_INSTALLATION_NAME,
    CONF_PREFIX,
    CONF_REGION,
    CONF_ROOT_PATH,
    CONF_SECRET_ACCESS_KEY,
    DEFAULT_BUCKET,
    DEFAULT_REGION,
    DEFAULT_ROOT_PATH,
    DOMAIN,
    PROBE_OBJECT_NAME,
    STORAGE_DIR,
)
from .utils import (
    build_storage_prefix,
    build_wasabi_endpoint,
    create_s3_client_config,
    normalize_region,
)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _probe_connection(
    *,
    key_id: str,
    secret: str,
    region: str,
    bucket: str,
    prefix: str,
) -> None:
    """Validate that the credentials can list, write, and delete objects."""

    async def _check() -> None:
        endpoint = build_wasabi_endpoint(region)
        probe_root = f"{prefix.strip('/')}/{STORAGE_DIR}/"
        probe_key = f"{probe_root}{PROBE_OBJECT_NAME}"
        session = AioSession()
        async with session.create_client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
            config=create_s3_client_config(),
        ) as client:
            await client.list_objects_v2(Bucket=bucket, Prefix=probe_root, MaxKeys=1)
            await client.put_object(Bucket=bucket, Key=probe_key, Body=b"")
            await client.delete_object(Bucket=bucket, Key=probe_key)

    asyncio.run(_check())


SCHEMA_SETUP = vol.Schema(
    {
        vol.Required(CONF_INSTALLATION_NAME): cv.string,
        vol.Required(CONF_BUCKET, default=DEFAULT_BUCKET): cv.string,
        vol.Required(CONF_ACCESS_KEY_ID): cv.string,
        vol.Required(CONF_SECRET_ACCESS_KEY): _PASSWORD,
        vol.Required(CONF_REGION, default=DEFAULT_REGION): cv.string,
        vol.Optional(CONF_ROOT_PATH, default=DEFAULT_ROOT_PATH): cv.string,
    }
)

SCHEMA_CREDENTIALS = vol.Schema(
    {
        vol.Required(CONF_ACCESS_KEY_ID): cv.string,
        vol.Required(CONF_SECRET_ACCESS_KEY): _PASSWORD,
    }
)

SCHEMA_FULL_EDIT = vol.Schema(
    {
        vol.Required(CONF_INSTALLATION_NAME): cv.string,
        vol.Required(CONF_BUCKET): cv.string,
        vol.Required(CONF_ACCESS_KEY_ID): cv.string,
        vol.Optional(CONF_SECRET_ACCESS_KEY): _PASSWORD,
        vol.Required(CONF_REGION): cv.string,
        vol.Optional(CONF_ROOT_PATH): cv.string,
    }
)


class NodaliaWasabiBackupsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Guide the user through setup, re-auth and reconfiguration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data, errors = self._prepare_data(user_input)
            if not errors and self._entry_exists(data[CONF_BUCKET], data[CONF_PREFIX]):
                return self.async_abort(reason="already_configured")
            if not errors:
                errors = await self._try_connect(data)
            if not errors:
                return self.async_create_entry(
                    title=data[CONF_INSTALLATION_NAME],
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA_SETUP, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Entry point for credential refresh."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update stored credentials."""
        errors: dict[str, str] = {}
        target = self._get_reauth_entry()

        if user_input is not None:
            merged = {**target.data, **user_input}
            errors = await self._try_connect(merged)
            if not errors:
                return self.async_update_reload_and_abort(
                    target,
                    data_updates={
                        CONF_ACCESS_KEY_ID: user_input[CONF_ACCESS_KEY_ID],
                        CONF_SECRET_ACCESS_KEY: user_input[CONF_SECRET_ACCESS_KEY],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_CREDENTIALS,
                {CONF_ACCESS_KEY_ID: target.data[CONF_ACCESS_KEY_ID]},
            ),
            errors=errors,
            description_placeholders={
                "bucket": target.data[CONF_BUCKET],
                "installation_name": target.data[CONF_INSTALLATION_NAME],
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the current configuration entry."""
        errors: dict[str, str] = {}
        target = self._get_reconfigure_entry()

        if user_input is not None:
            submitted = dict(user_input)
            if not submitted.get(CONF_SECRET_ACCESS_KEY):
                submitted[CONF_SECRET_ACCESS_KEY] = target.data[CONF_SECRET_ACCESS_KEY]
            data, errors = self._prepare_data({**target.data, **submitted})
            if (
                not errors
                and self._entry_exists(
                    data[CONF_BUCKET],
                    data[CONF_PREFIX],
                    ignore_entry_id=target.entry_id,
                )
            ):
                return self.async_abort(reason="already_configured")
            if not errors:
                errors = await self._try_connect(data)
            if not errors:
                return self.async_update_reload_and_abort(
                    target,
                    data_updates=data,
                    title=data[CONF_INSTALLATION_NAME],
                )

        suggested_values = {
            key: value
            for key, value in target.data.items()
            if key in {
                CONF_INSTALLATION_NAME,
                CONF_BUCKET,
                CONF_ACCESS_KEY_ID,
                CONF_REGION,
                CONF_ROOT_PATH,
            }
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_FULL_EDIT, suggested_values
            ),
            errors=errors,
        )

    def _prepare_data(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Normalize user input and derive the internal prefix."""
        data = dict(user_input)
        errors: dict[str, str] = {}

        data[CONF_INSTALLATION_NAME] = data[CONF_INSTALLATION_NAME].strip()
        data[CONF_BUCKET] = data[CONF_BUCKET].strip()
        data[CONF_ROOT_PATH] = data.get(CONF_ROOT_PATH, DEFAULT_ROOT_PATH).strip()

        try:
            data[CONF_REGION] = normalize_region(data.get(CONF_REGION, DEFAULT_REGION))
        except ValueError:
            errors[CONF_REGION] = "invalid_region"

        if not data[CONF_INSTALLATION_NAME]:
            errors[CONF_INSTALLATION_NAME] = "invalid_installation_name"

        if not data[CONF_BUCKET]:
            errors[CONF_BUCKET] = "invalid_bucket_name"

        if not errors:
            try:
                data[CONF_PREFIX] = build_storage_prefix(
                    data[CONF_ROOT_PATH], data[CONF_INSTALLATION_NAME]
                )
            except ValueError:
                errors[CONF_INSTALLATION_NAME] = "invalid_installation_name"

        return data, errors

    def _entry_exists(
        self, bucket: str, prefix: str, ignore_entry_id: str | None = None
    ) -> bool:
        """Return True when another entry already owns the same bucket/prefix."""
        for entry in self._async_current_entries():
            if ignore_entry_id and entry.entry_id == ignore_entry_id:
                continue
            if (
                entry.data.get(CONF_BUCKET) == bucket
                and entry.data.get(CONF_PREFIX) == prefix
            ):
                return True
        return False

    async def _try_connect(self, data: dict[str, Any]) -> dict[str, str]:
        """Probe Wasabi and map low-level failures to UI errors."""
        try:
            await self.hass.async_add_executor_job(
                functools.partial(
                    _probe_connection,
                    key_id=data[CONF_ACCESS_KEY_ID],
                    secret=data[CONF_SECRET_ACCESS_KEY],
                    region=data[CONF_REGION],
                    bucket=data[CONF_BUCKET],
                    prefix=data[CONF_PREFIX],
                )
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchBucket", "404"}:
                return {CONF_BUCKET: "bucket_not_found"}
            return {"base": "invalid_credentials"}
        except ParamValidationError as exc:
            if "Invalid bucket name" in str(exc):
                return {CONF_BUCKET: "invalid_bucket_name"}
        except ValueError:
            return {CONF_REGION: "invalid_region"}
        except BotoConnectionError:
            return {"base": "cannot_connect"}
        return {}
