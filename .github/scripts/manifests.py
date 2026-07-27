#!/usr/bin/env python3
"""
Shared manifest I/O for schema-aggregator -- used by both sync_sources.py
and remove_source.py. Lives in its own module rather than inside either of
those two files: sync_sources.py already imports remove_source.py (for
orphan reconciliation), so putting this in either one and importing it
from the other would be a circular import.

Manifest file format: {"schemas": [...], "last_synced": "<ISO 8601 UTC>"}.
Manifests committed before this format existed are a bare JSON array of
schema names -- load_manifest_schemas() reads both shapes, so there's no
forced migration; a source just has no last_synced recorded until it's
next synced under this code.
"""

import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.getcwd()
MANIFEST_DIR = os.path.join(REPO_ROOT, ".sync")


def manifest_path(source_id):
    return os.path.join(MANIFEST_DIR, f"manifest-{source_id}.json")


def failures_path(source_id):
    return os.path.join(MANIFEST_DIR, f"failures-{source_id}.json")


def _load_manifest_data(source_id):
    """Returns {"schemas": [...], "last_synced": str|None}, or None if this
    source has never been synced. Normalizes the old bare-array shape into
    the same dict form so callers never need to know which one is on disk."""
    path = manifest_path(source_id)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"schemas": data, "last_synced": None}
    return data


def load_manifest_schemas(source_id):
    data = _load_manifest_data(source_id)
    return set(data["schemas"]) if data else set()


def load_manifest_synced_at(source_id):
    data = _load_manifest_data(source_id)
    return data["last_synced"] if data else None


def write_manifest(source_id, schemas):
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    data = {
        "schemas": sorted(schemas),
        "last_synced": datetime.now(timezone.utc).isoformat(),
    }
    with open(manifest_path(source_id), "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
