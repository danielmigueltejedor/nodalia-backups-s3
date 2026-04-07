"""Tests for the backup agent."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError

from custom_components.nodalia_backups_s3.backup import (
    CHUNK_THRESHOLD_BYTES,
    NodaliaWasabiBackupAgent,
    _derive_object_names,
    _wrap_storage_errors,
    async_get_backup_agents,
    async_register_backup_agents_listener,
)
from custom_components.nodalia_backups_s3.const import (
    AGENT_LISTENER_KEY,
    CONF_BUCKET,
    CONF_INSTALLATION_NAME,
    CONF_PREFIX,
    CONF_ROOT_PATH,
    DEFAULT_ROOT_PATH,
    DOMAIN,
    STORAGE_DIR,
)


def _make_agent(
    mock_gateway, bucket="nodalia-backups", prefix="homeassistant/cliente-demo"
):
    entry = MagicMock()
    entry.runtime_data = mock_gateway
    entry.data = {
        CONF_BUCKET: bucket,
        CONF_PREFIX: prefix,
        CONF_ROOT_PATH: DEFAULT_ROOT_PATH,
        CONF_INSTALLATION_NAME: "Cliente Demo",
    }
    entry.title = "Cliente Demo"
    entry.entry_id = "entry-1"
    hass = MagicMock()
    return NodaliaWasabiBackupAgent(hass, entry)


def _backup_dict(backup_id="abc-123", name="Backup diario"):
    return {
        "backup_id": backup_id,
        "name": name,
        "date": "2026-04-07T20:00:00.000000+00:00",
        "size": 1024,
        "protected": False,
        "extra_metadata": {},
        "addons": [],
        "agents": {},
        "database_included": True,
        "folders": [],
        "homeassistant_included": True,
        "homeassistant_version": "2026.4.0",
    }


class TestHelpers:
    def test_derive_object_names(self):
        backup = MagicMock()
        with patch(
            "custom_components.nodalia_backups_s3.backup.suggested_filename",
            return_value="backup.tar",
        ):
            tar_name, metadata_name = _derive_object_names(backup)

        assert tar_name == "backup.tar"
        assert metadata_name == "backup.metadata.json"

    async def test_wrap_storage_errors_translates_boto(self):
        from homeassistant.components.backup import BackupAgentError

        @_wrap_storage_errors
        async def broken():
            raise BotoCoreError()

        with pytest.raises(BackupAgentError):
            await broken()


class TestAgentConstruction:
    def test_domain(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        assert agent.domain == DOMAIN

    def test_root_uses_prefix(self, mock_gateway):
        agent = _make_agent(mock_gateway, prefix="homeassistant/demo")
        assert agent._root == f"homeassistant/demo/{STORAGE_DIR}/"


class TestListing:
    async def test_lists_metadata_files(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        body = AsyncMock()
        body.read = AsyncMock(return_value=json.dumps(_backup_dict()).encode())

        mock_gateway.list_objects_v2.return_value = {
            "Contents": [
                {"Key": f"{agent._root}backup.tar"},
                {"Key": f"{agent._root}backup.metadata.json"},
            ],
            "IsTruncated": False,
        }
        mock_gateway.get_object.return_value = {"Body": body}

        result = await agent.async_list_backups()
        assert len(result) == 1
        assert result[0].backup_id == "abc-123"

    async def test_skips_invalid_metadata(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        body = AsyncMock()
        body.read = AsyncMock(return_value=b"not-json")

        mock_gateway.list_objects_v2.return_value = {
            "Contents": [{"Key": f"{agent._root}broken.metadata.json"}],
            "IsTruncated": False,
        }
        mock_gateway.get_object.return_value = {"Body": body}

        result = await agent.async_list_backups()
        assert result == []


class TestDownloadDeleteUpload:
    async def test_delete_removes_archive_and_metadata(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        body = AsyncMock()
        body.read = AsyncMock(return_value=json.dumps(_backup_dict("del-1")).encode())
        mock_gateway.list_objects_v2.return_value = {
            "Contents": [{"Key": f"{agent._root}backup.metadata.json"}],
            "IsTruncated": False,
        }
        mock_gateway.get_object.return_value = {"Body": body}

        with patch(
            "custom_components.nodalia_backups_s3.backup.suggested_filename",
            return_value="del-1.tar",
        ):
            await agent.async_delete_backup("del-1")

        assert mock_gateway.delete_object.call_count == 2

    async def test_small_upload_uses_put_object(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        backup = MagicMock()
        backup.size = 100
        backup.as_dict.return_value = _backup_dict()

        async def open_stream():
            async def generator():
                yield b"small payload"

            return generator()

        with patch(
            "custom_components.nodalia_backups_s3.backup.suggested_filename",
            return_value="small.tar",
        ):
            await agent.async_upload_backup(open_stream=open_stream, backup=backup)

        mock_gateway.put_object.assert_called()
        mock_gateway.create_multipart_upload.assert_not_called()

    async def test_large_upload_uses_multipart(self, mock_gateway):
        agent = _make_agent(mock_gateway)
        backup = MagicMock()
        backup.size = CHUNK_THRESHOLD_BYTES + 1
        backup.as_dict.return_value = _backup_dict()
        payload = b"x" * (CHUNK_THRESHOLD_BYTES + 10)

        async def open_stream():
            async def generator():
                yield payload

            return generator()

        with patch(
            "custom_components.nodalia_backups_s3.backup.suggested_filename",
            return_value="large.tar",
        ):
            await agent.async_upload_backup(open_stream=open_stream, backup=backup)

        mock_gateway.create_multipart_upload.assert_called_once()
        mock_gateway.upload_part.assert_called()
        mock_gateway.complete_multipart_upload.assert_called_once()

    async def test_failed_multipart_is_aborted(self, mock_gateway):
        from homeassistant.components.backup import BackupAgentError

        agent = _make_agent(mock_gateway)
        backup = MagicMock()
        backup.size = CHUNK_THRESHOLD_BYTES + 1
        backup.as_dict.return_value = _backup_dict()
        mock_gateway.upload_part.side_effect = BotoCoreError()
        payload = b"x" * (CHUNK_THRESHOLD_BYTES + 10)

        async def open_stream():
            async def generator():
                yield payload

            return generator()

        with (
            patch(
                "custom_components.nodalia_backups_s3.backup.suggested_filename",
                return_value="broken.tar",
            ),
            pytest.raises(BackupAgentError),
        ):
            await agent.async_upload_backup(open_stream=open_stream, backup=backup)

        mock_gateway.abort_multipart_upload.assert_called_once()


class TestModuleHelpers:
    async def test_get_backup_agents_returns_entries(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.runtime_data = MagicMock()
        entry.data = {
            CONF_BUCKET: "nodalia-backups",
            CONF_PREFIX: "homeassistant/demo",
            CONF_ROOT_PATH: DEFAULT_ROOT_PATH,
            CONF_INSTALLATION_NAME: "Demo",
        }
        entry.title = "Demo"
        entry.entry_id = "entry-1"
        hass.config_entries.async_loaded_entries.return_value = [entry]

        agents = await async_get_backup_agents(hass)
        assert len(agents) == 1
        assert isinstance(agents[0], NodaliaWasabiBackupAgent)

    def test_listener_registration_returns_unsubscribe(self):
        hass = MagicMock()
        hass.data = {}
        listener = MagicMock()

        unsubscribe = async_register_backup_agents_listener(hass, listener=listener)
        assert callable(unsubscribe)
        assert listener in hass.data[AGENT_LISTENER_KEY]

        unsubscribe()
        assert AGENT_LISTENER_KEY not in hass.data
