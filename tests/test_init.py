"""Tests for integration setup helpers."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.nodalia_backups_s3 import WasabiStorageGateway
from custom_components.nodalia_backups_s3.const import STORAGE_DIR


def _executor_side_effect(job):
    return job()


class TestWasabiStorageGateway:
    async def test_async_start_and_stop_manage_client_lifecycle(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=_executor_side_effect)

        client = MagicMock()
        client.list_objects_v2.return_value = {}
        client.close = MagicMock()

        gateway = WasabiStorageGateway(
            hass=hass,
            key_id="ACCESS",
            secret="SECRET",
            region="eu-west-2",
            bucket="nodalia-backups",
            prefix="homeassistant/demo",
        )
        gateway._create_client = MagicMock(return_value=client)

        await gateway.async_start()

        gateway._create_client.assert_called_once_with()
        client.list_objects_v2.assert_called_once_with(
            Bucket="nodalia-backups",
            Prefix=f"homeassistant/demo/{STORAGE_DIR}/",
            MaxKeys=1,
        )
        assert gateway._client is client

        await gateway.async_stop()

        client.close.assert_called_once_with()
        assert gateway._client is None

    async def test_get_object_wraps_streaming_body(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=_executor_side_effect)

        raw_body = MagicMock()
        raw_body.read = MagicMock(side_effect=[b"chunk-1", b""])
        raw_body.close = MagicMock()

        client = MagicMock()
        client.get_object.return_value = {"Body": raw_body}

        gateway = WasabiStorageGateway(
            hass=hass,
            key_id="ACCESS",
            secret="SECRET",
            region="eu-west-2",
            bucket="nodalia-backups",
            prefix="homeassistant/demo",
        )
        gateway._client = client

        response = await gateway.get_object(Bucket="nodalia-backups", Key="test.tar")
        body = response["Body"]

        assert await body.read(7) == b"chunk-1"
        assert [chunk async for chunk in body.iter_chunks(7)] == []
        raw_body.close.assert_called()
