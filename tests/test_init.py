"""Tests for integration setup helpers."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.nodalia_backups_s3 import WasabiStorageGateway
from custom_components.nodalia_backups_s3.const import STORAGE_DIR


class TestWasabiStorageGateway:
    async def test_async_start_and_stop_manage_client_context(self):
        client = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)

        gateway = WasabiStorageGateway(
            key_id="ACCESS",
            secret="SECRET",
            region="eu-west-2",
            bucket="nodalia-backups",
            prefix="homeassistant/demo",
        )
        gateway._session = MagicMock()
        gateway._session.create_client.return_value = context

        await gateway.async_start()

        context.__aenter__.assert_awaited_once()
        client.list_objects_v2.assert_awaited_once_with(
            Bucket="nodalia-backups",
            Prefix=f"homeassistant/demo/{STORAGE_DIR}/",
            MaxKeys=1,
        )
        assert gateway._client is client

        await gateway.async_stop()

        context.__aexit__.assert_awaited_once_with(None, None, None)
        assert gateway._client is None
        assert gateway._client_context is None
