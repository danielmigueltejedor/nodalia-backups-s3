"""Tests for config-flow helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import (
    ClientError,
    ConnectionError as BotoConnectionError,
    ParamValidationError,
)

from custom_components.nodalia_backups_s3.config_flow import (
    SCHEMA_SETUP,
    _probe_connection,
    NodaliaWasabiBackupsConfigFlow,
)
from custom_components.nodalia_backups_s3.const import (
    CONF_BUCKET,
    CONF_INSTALLATION_NAME,
    CONF_PREFIX,
    CONF_REGION,
    DEFAULT_REGION,
)


class TestProbeConnection:
    """Tests for the synchronous Wasabi connection probe."""

    @patch("custom_components.nodalia_backups_s3.config_flow.AioSession")
    def test_success(self, mock_session_cls):
        mock_client = AsyncMock()
        mock_client.list_objects_v2 = AsyncMock(return_value={})
        mock_client.put_object = AsyncMock(return_value={})
        mock_client.delete_object = AsyncMock(return_value={})

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_client)
        context.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.create_client.return_value = context
        mock_session_cls.return_value = mock_session

        _probe_connection(
            key_id="ACCESS",
            secret="SECRET",
            region="eu-central-1",
            bucket="nodalia-demo",
            prefix="clients/demo",
        )

    @patch("custom_components.nodalia_backups_s3.config_flow.AioSession")
    def test_client_error_propagates(self, mock_session_cls):
        mock_client = AsyncMock()
        mock_client.list_objects_v2 = AsyncMock(
            side_effect=ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
                "ListObjectsV2",
            )
        )

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_client)
        context.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.create_client.return_value = context
        mock_session_cls.return_value = mock_session

        with pytest.raises(ClientError):
            _probe_connection(
                key_id="ACCESS",
                secret="SECRET",
                region="eu-central-1",
                bucket="nodalia-demo",
                prefix="clients/demo",
            )

    @patch("custom_components.nodalia_backups_s3.config_flow.AioSession")
    def test_connection_error_propagates(self, mock_session_cls):
        mock_client = AsyncMock()
        mock_client.list_objects_v2 = AsyncMock(
            side_effect=BotoConnectionError(error="unreachable")
        )

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_client)
        context.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.create_client.return_value = context
        mock_session_cls.return_value = mock_session

        with pytest.raises(BotoConnectionError):
            _probe_connection(
                key_id="ACCESS",
                secret="SECRET",
                region="eu-central-1",
                bucket="nodalia-demo",
                prefix="clients/demo",
            )


class TestPrepareData:
    """Tests for config normalization and validation."""

    @pytest.fixture
    def flow(self):
        config_flow = NodaliaWasabiBackupsConfigFlow()
        config_flow.hass = MagicMock()
        config_flow.hass.async_add_executor_job = AsyncMock()
        return config_flow

    async def test_prepare_data_builds_prefix(self, flow):
        data, errors = flow._prepare_data(
            {
                "installation_name": "Cliente Demo",
                "bucket": "nodalia-demo",
                "access_key_id": "ACCESS",
                "secret_access_key": "SECRET",
                "region": "EU-CENTRAL-1",
                "root_path": "Clientes",
            }
        )

        assert errors == {}
        assert data[CONF_REGION] == "eu-central-1"
        assert data[CONF_PREFIX] == "clientes/cliente-demo"

    async def test_prepare_data_rejects_empty_installation_name(self, flow):
        _, errors = flow._prepare_data(
            {
                "installation_name": "///",
                "bucket": "nodalia-demo",
                "access_key_id": "ACCESS",
                "secret_access_key": "SECRET",
                "region": "eu-central-1",
                "root_path": "clients",
            }
        )

        assert errors == {CONF_INSTALLATION_NAME: "invalid_installation_name"}

    async def test_try_connect_maps_bucket_error(self, flow, sample_config):
        flow.hass.async_add_executor_job.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "Not Found"}},
            "ListObjectsV2",
        )

        errors = await flow._try_connect(sample_config)
        assert errors == {CONF_BUCKET: "bucket_not_found"}

    async def test_try_connect_maps_credentials_error(self, flow, sample_config):
        flow.hass.async_add_executor_job.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "ListObjectsV2",
        )

        errors = await flow._try_connect(sample_config)
        assert errors == {"base": "invalid_credentials"}

    async def test_try_connect_maps_invalid_bucket_name(self, flow, sample_config):
        flow.hass.async_add_executor_job.side_effect = ParamValidationError(
            report="Invalid bucket name"
        )

        errors = await flow._try_connect(sample_config)
        assert errors == {CONF_BUCKET: "invalid_bucket_name"}


class TestSchemas:
    """Basic schema checks."""

    def test_setup_schema_contains_expected_fields(self):
        schema_keys = {str(key) for key in SCHEMA_SETUP.schema}
        assert CONF_INSTALLATION_NAME in schema_keys
        assert CONF_BUCKET in schema_keys
        assert CONF_REGION in schema_keys

    def test_setup_schema_uses_default_region(self):
        for key in SCHEMA_SETUP.schema:
            if str(key) == CONF_REGION:
                assert key.default() == DEFAULT_REGION
