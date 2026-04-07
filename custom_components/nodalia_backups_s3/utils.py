"""Helper functions for Wasabi endpoint and prefix handling."""

from __future__ import annotations

import re

from botocore.config import Config

from .const import DEFAULT_ROOT_PATH, WASABI_ENDPOINT_TEMPLATE

_INVALID_SEGMENT_CHARS = re.compile(r"[^a-z0-9-]+")
_MULTIPLE_DASHES = re.compile(r"-{2,}")
_REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")


def create_s3_client_config() -> Config:
    """Return the shared botocore config for Wasabi access."""
    return Config(
        connect_timeout=10,
        read_timeout=60,
        retries={"max_attempts": 3, "mode": "standard"},
        s3={"addressing_style": "path"},
    )


def slugify_segment(value: str) -> str:
    """Convert a user-facing name into a stable object-storage path segment."""
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("_", "-")
    cleaned = cleaned.replace("/", "-")
    cleaned = _INVALID_SEGMENT_CHARS.sub("-", cleaned)
    cleaned = _MULTIPLE_DASHES.sub("-", cleaned).strip("-")
    if not cleaned:
        raise ValueError("invalid_installation_name")
    return cleaned


def normalize_root_path(value: str) -> str:
    """Normalize the configurable parent path for client prefixes."""
    raw = value.strip() or DEFAULT_ROOT_PATH
    parts: list[str] = []
    for part in raw.split("/"):
        part = part.strip()
        if not part:
            continue
        parts.append(slugify_segment(part))
    return "/".join(parts)


def normalize_region(value: str) -> str:
    """Validate and normalize a Wasabi region string."""
    region = value.strip().lower()
    if not region or not _REGION_PATTERN.fullmatch(region):
        raise ValueError("invalid_region")
    return region


def build_storage_prefix(root_path: str, installation_name: str) -> str:
    """Build the storage prefix used to isolate one customer installation."""
    parent = normalize_root_path(root_path)
    installation = slugify_segment(installation_name)
    return f"{parent}/{installation}" if parent else installation


def build_wasabi_endpoint(region: str) -> str:
    """Build a Wasabi S3 endpoint from a region."""
    return WASABI_ENDPOINT_TEMPLATE.format(region=normalize_region(region))
