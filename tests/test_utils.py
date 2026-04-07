"""Tests for helper utilities."""

import pytest

from custom_components.nodalia_backups_s3.utils import (
    append_storage_subpath,
    build_entry_title,
    build_storage_prefix,
    build_wasabi_endpoint,
    normalize_installation_path,
    normalize_root_path,
    slugify_segment,
)


def test_slugify_segment_normalizes_text():
    assert slugify_segment("Cliente Demo") == "cliente-demo"


def test_slugify_segment_rejects_empty_values():
    with pytest.raises(ValueError):
        slugify_segment("   ")


def test_normalize_installation_path_keeps_nested_structure():
    assert (
        normalize_installation_path("Cliente Demo / Casa 1")
        == "cliente-demo/casa-1"
    )


def test_normalize_installation_path_rejects_only_separators():
    with pytest.raises(ValueError):
        normalize_installation_path("///")


def test_normalize_root_path_keeps_nested_structure():
    assert normalize_root_path("Clientes VIP/Madrid") == "clientes-vip/madrid"


def test_build_storage_prefix_combines_root_and_slug():
    assert (
        build_storage_prefix("Clientes", "Casa Daniel")
        == "clientes/casa-daniel"
    )


def test_build_storage_prefix_preserves_subfolders_in_installation_name():
    assert (
        build_storage_prefix("homeassistant", "cliente/casa1")
        == "homeassistant/cliente/casa1"
    )


def test_append_storage_subpath_adds_additional_house():
    assert (
        append_storage_subpath("homeassistant/cliente", "casa1")
        == "homeassistant/cliente/casa1"
    )


def test_append_storage_subpath_keeps_prefix_when_empty():
    assert append_storage_subpath("homeassistant/cliente", "") == "homeassistant/cliente"


def test_build_entry_title_uses_additional_house_when_present():
    assert build_entry_title("Cliente Demo", "Casa 1") == "Cliente Demo / Casa 1"


def test_build_wasabi_endpoint_uses_region():
    assert (
        build_wasabi_endpoint("EU-WEST-2")
        == "https://s3.eu-west-2.wasabisys.com"
    )
