"""Tests for helper utilities."""

import pytest

from custom_components.nodalia_backups_s3.utils import (
    build_storage_prefix,
    build_wasabi_endpoint,
    normalize_root_path,
    slugify_segment,
)


def test_slugify_segment_normalizes_text():
    assert slugify_segment("Cliente Demo / Piso 1") == "cliente-demo-piso-1"


def test_slugify_segment_rejects_empty_values():
    with pytest.raises(ValueError):
        slugify_segment("///")


def test_normalize_root_path_keeps_nested_structure():
    assert normalize_root_path("Clientes VIP/Madrid") == "clientes-vip/madrid"


def test_build_storage_prefix_combines_root_and_slug():
    assert (
        build_storage_prefix("Clientes", "Casa Daniel")
        == "clientes/casa-daniel"
    )


def test_build_wasabi_endpoint_uses_region():
    assert (
        build_wasabi_endpoint("EU-WEST-2")
        == "https://s3.eu-west-2.wasabisys.com"
    )
