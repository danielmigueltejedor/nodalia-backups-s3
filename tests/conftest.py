"""Shared fixtures for Nodalia Wasabi Backups tests."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if "lru" not in sys.modules:
    lru_module = types.ModuleType("lru")

    class _LRU(dict):
        def __init__(self, maxsize: int = 128, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._maxsize = maxsize

        def get_size(self):
            return self._maxsize

    lru_module.LRU = _LRU  # type: ignore[attr-defined]
    sys.modules["lru"] = lru_module

try:
    from homeassistant.components.backup import BackupNotFound  # noqa: F401
except ImportError:
    import homeassistant.components.backup as backup_module

    class _BackupNotFound(Exception):
        """Placeholder for older Home Assistant versions."""

    backup_module.BackupNotFound = _BackupNotFound  # type: ignore[attr-defined]

try:
    from homeassistant.components.backup import suggested_filename  # noqa: F401
except ImportError:
    import homeassistant.components.backup as backup_module

    def _suggested_filename(backup):
        return f"{backup.backup_id}.tar"

    backup_module.suggested_filename = _suggested_filename  # type: ignore[attr-defined]


@pytest.fixture
def mock_gateway():
    """Return a fully mocked Wasabi gateway."""
    gateway = MagicMock()
    gateway.async_start = AsyncMock()
    gateway.async_stop = AsyncMock()
    gateway.head_bucket = AsyncMock(return_value={})
    gateway.list_objects_v2 = AsyncMock(return_value={"Contents": [], "IsTruncated": False})
    gateway.get_object = AsyncMock()
    gateway.put_object = AsyncMock()
    gateway.delete_object = AsyncMock()
    gateway.create_multipart_upload = AsyncMock(return_value={"UploadId": "test-upload"})
    gateway.upload_part = AsyncMock(return_value={"ETag": '"etag-value"'})
    gateway.complete_multipart_upload = AsyncMock()
    gateway.abort_multipart_upload = AsyncMock()
    return gateway


@pytest.fixture
def sample_config():
    """Return a representative config-entry payload."""
    return {
        "installation_name": "Cliente Demo",
        "additional_house": "",
        "bucket": "nodalia-backups",
        "access_key_id": "ACCESS123",
        "secret_access_key": "SECRET123",
        "region": "eu-west-2",
        "root_path": "homeassistant",
        "prefix": "homeassistant/cliente-demo",
    }


@pytest.fixture
def mock_probe_connection():
    """Patch the Wasabi probe helper so it succeeds."""
    with patch(
        "custom_components.nodalia_backups_s3.config_flow._probe_connection"
    ) as mocked:
        mocked.return_value = None
        yield mocked
