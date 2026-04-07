"""Backup agent implementation for Nodalia Wasabi Backups."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
import functools
import json
import logging
from time import monotonic
from typing import Any, TypeVar

from botocore.exceptions import BotoCoreError

from homeassistant.components.backup import (
    AgentBackup,
    BackupAgent,
    BackupAgentError,
    BackupNotFound,
    suggested_filename,
)
from homeassistant.core import HomeAssistant, callback

from . import NodaliaBackupsEntry, WasabiStorageGateway
from .const import (
    AGENT_LISTENER_KEY,
    CONF_BUCKET,
    CONF_INSTALLATION_NAME,
    CONF_PREFIX,
    CONF_ROOT_PATH,
    DEFAULT_ROOT_PATH,
    DOMAIN,
    SERVER_SIDE_ENCRYPTION,
    STORAGE_DIR,
)
from .utils import build_storage_prefix

_LOGGER = logging.getLogger(__name__)

LISTING_CACHE_SECONDS = 300
CHUNK_THRESHOLD_BYTES = 20 * 2**20
T = TypeVar("T")


def _wrap_storage_errors(
    func: Callable[..., Coroutine[Any, Any, T]],
) -> Callable[..., Coroutine[Any, Any, T]]:
    """Translate boto exceptions into Home Assistant backup errors."""

    @functools.wraps(func)
    async def _inner(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except BotoCoreError as exc:
            raise BackupAgentError(f"{func.__name__} failed") from exc

    return _inner


async def async_get_backup_agents(hass: HomeAssistant) -> list[BackupAgent]:
    """Return one backup agent for each loaded config entry."""
    entries: list[NodaliaBackupsEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    return [NodaliaWasabiBackupAgent(hass, entry) for entry in entries]


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant,
    *,
    listener: Callable[[], None],
    **kwargs: Any,
) -> Callable[[], None]:
    """Subscribe to agent add/remove notifications."""
    listeners = hass.data.setdefault(AGENT_LISTENER_KEY, [])
    listeners.append(listener)

    @callback
    def _unsubscribe() -> None:
        listeners.remove(listener)
        if not listeners:
            del hass.data[AGENT_LISTENER_KEY]

    return _unsubscribe


def _derive_object_names(backup: AgentBackup) -> tuple[str, str]:
    """Return the tarball name and sidecar metadata name."""
    stem = suggested_filename(backup).rsplit(".", 1)[0]
    return f"{stem}.tar", f"{stem}.metadata.json"


class NodaliaWasabiBackupAgent(BackupAgent):
    """Store Home Assistant backups in a Wasabi bucket."""

    domain = DOMAIN

    def __init__(self, hass: HomeAssistant, entry: NodaliaBackupsEntry) -> None:
        super().__init__()
        self._gateway: WasabiStorageGateway = entry.runtime_data
        self._bucket: str = entry.data[CONF_BUCKET]
        self._root = self._resolve_root(entry)
        self.name = entry.title
        self.unique_id = entry.entry_id
        self._listing: dict[str, AgentBackup] = {}
        self._listing_valid_until = 0.0

    @staticmethod
    def _resolve_root(entry: NodaliaBackupsEntry) -> str:
        """Normalize the object-storage root used for backups."""
        prefix = entry.data.get(CONF_PREFIX)
        if not prefix:
            prefix = build_storage_prefix(
                entry.data.get(CONF_ROOT_PATH, DEFAULT_ROOT_PATH),
                entry.data.get(CONF_INSTALLATION_NAME, entry.title),
            )
        segment = prefix.strip("/")
        return f"{segment}/{STORAGE_DIR}/" if segment else f"{STORAGE_DIR}/"

    def _key(self, name: str) -> str:
        """Build a full object key inside the configured backup root."""
        return f"{self._root}{name}"

    @_wrap_storage_errors
    async def async_download_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Stream a backup archive from Wasabi."""
        tar_name, _ = _derive_object_names(await self._resolve(backup_id))
        response = await self._gateway.get_object(
            Bucket=self._bucket,
            Key=self._key(tar_name),
        )
        return response["Body"].iter_chunks()

    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        **kwargs: Any,
    ) -> None:
        """Upload a backup archive and its metadata sidecar."""
        tar_name, meta_name = _derive_object_names(backup)

        try:
            if backup.size < CHUNK_THRESHOLD_BYTES:
                await self._put_single(self._key(tar_name), open_stream)
            else:
                await self._put_chunked(self._key(tar_name), open_stream)

            metadata = json.dumps(backup.as_dict()).encode("utf-8")
            await self._gateway.put_object(
                Bucket=self._bucket,
                Key=self._key(meta_name),
                Body=metadata,
                ContentType="application/json",
                ServerSideEncryption=SERVER_SIDE_ENCRYPTION,
            )
        except BotoCoreError as exc:
            raise BackupAgentError("Upload failed") from exc
        else:
            self._drop_cache()

    @_wrap_storage_errors
    async def async_delete_backup(self, backup_id: str, **kwargs: Any) -> None:
        """Delete a backup archive and its metadata."""
        tar_name, meta_name = _derive_object_names(await self._resolve(backup_id))
        await self._gateway.delete_object(Bucket=self._bucket, Key=self._key(tar_name))
        await self._gateway.delete_object(
            Bucket=self._bucket, Key=self._key(meta_name)
        )
        self._drop_cache()

    @_wrap_storage_errors
    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """Return all backups visible in the configured prefix."""
        return list((await self._fetch_listing()).values())

    @_wrap_storage_errors
    async def async_get_backup(self, backup_id: str, **kwargs: Any) -> AgentBackup:
        """Return one backup by id or raise BackupNotFound."""
        return await self._resolve(backup_id)

    async def _resolve(self, backup_id: str) -> AgentBackup:
        """Resolve one backup from the cached or remote listing."""
        listing = await self._fetch_listing()
        if (backup := listing.get(backup_id)) is not None:
            return backup
        raise BackupNotFound(f"Backup {backup_id} not found")

    def _drop_cache(self) -> None:
        """Invalidate the in-memory listing cache."""
        self._listing = {}
        self._listing_valid_until = 0.0

    async def _fetch_listing(self) -> dict[str, AgentBackup]:
        """Fetch metadata sidecars and build the backup listing."""
        if monotonic() <= self._listing_valid_until:
            return self._listing

        result: dict[str, AgentBackup] = {}
        continuation_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": self._root,
            }
            if continuation_token:
                params["ContinuationToken"] = continuation_token

            page = await self._gateway.list_objects_v2(**params)

            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".metadata.json"):
                    continue
                try:
                    response = await self._gateway.get_object(
                        Bucket=self._bucket,
                        Key=obj["Key"],
                    )
                    raw = await response["Body"].read()
                    parsed = AgentBackup.from_dict(json.loads(raw))
                except (BotoCoreError, json.JSONDecodeError) as exc:
                    _LOGGER.warning("Skipping %s: %s", obj["Key"], exc)
                    continue
                result[parsed.backup_id] = parsed

            if page.get("IsTruncated"):
                continuation_token = page.get("NextContinuationToken")
            else:
                break

        self._listing = result
        self._listing_valid_until = monotonic() + LISTING_CACHE_SECONDS
        return self._listing

    async def _put_single(
        self,
        key: str,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
    ) -> None:
        """Upload small backups with one PutObject request."""
        buffer = bytearray()
        async for chunk in await open_stream():
            buffer.extend(chunk)

        await self._gateway.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=bytes(buffer),
            ContentType="application/x-tar",
            ServerSideEncryption=SERVER_SIDE_ENCRYPTION,
        )

    async def _put_chunked(
        self,
        key: str,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
    ) -> None:
        """Upload large backups as multipart objects."""
        multipart = await self._gateway.create_multipart_upload(
            Bucket=self._bucket,
            Key=key,
            ContentType="application/x-tar",
            ServerSideEncryption=SERVER_SIDE_ENCRYPTION,
        )
        upload_id = multipart["UploadId"]

        try:
            completed_parts: list[dict[str, Any]] = []
            part_number = 1
            buffer = bytearray()

            async for chunk in await open_stream():
                buffer.extend(chunk)
                while len(buffer) >= CHUNK_THRESHOLD_BYTES:
                    segment = bytes(buffer[:CHUNK_THRESHOLD_BYTES])
                    del buffer[:CHUNK_THRESHOLD_BYTES]
                    part = await self._gateway.upload_part(
                        Bucket=self._bucket,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=segment,
                    )
                    completed_parts.append(
                        {"PartNumber": part_number, "ETag": part["ETag"]}
                    )
                    part_number += 1

            if buffer:
                part = await self._gateway.upload_part(
                    Bucket=self._bucket,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=bytes(buffer),
                )
                completed_parts.append(
                    {"PartNumber": part_number, "ETag": part["ETag"]}
                )

            await self._gateway.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": completed_parts},
            )
        except BotoCoreError:
            try:
                await self._gateway.abort_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                )
            except BotoCoreError:
                _LOGGER.exception("Could not abort multipart upload %s", upload_id)
            raise
