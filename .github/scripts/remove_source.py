#!/usr/bin/env python3
"""
Manifest-driven cleanup for a removed source. Called by sources-changed.yml
for each source id that was present in sources.yaml before a push and is
missing after it.

Reuses .sync/manifest-<source_id>.json -- the same file the sync workflow
already maintains to know which classes a source owns -- rather than
inventing new bookkeeping. Deletes every class it lists, skipping any class
that's also currently claimed by another source's manifest (doesn't happen
today given no name collisions exist across the registered sources, but
cheap to guard against), then deletes the source's manifest and failures
files.

Usage: remove_source.py <source_id>
"""

import json
import os
import shutil
import sys

REPO_ROOT = os.getcwd()
MANIFEST_DIR = os.path.join(REPO_ROOT, ".sync")


def manifest_path(source_id):
    return os.path.join(MANIFEST_DIR, f"manifest-{source_id}.json")


def failures_path(source_id):
    return os.path.join(MANIFEST_DIR, f"failures-{source_id}.json")


def other_sources_manifests(excluding_id):
    if not os.path.isdir(MANIFEST_DIR):
        return {}
    others = {}
    for fname in os.listdir(MANIFEST_DIR):
        if not (fname.startswith("manifest-") and fname.endswith(".json")):
            continue
        other_id = fname[len("manifest-"):-len(".json")]
        if other_id == excluding_id:
            continue
        with open(os.path.join(MANIFEST_DIR, fname)) as f:
            others[other_id] = set(json.load(f))
    return others


def remove_source(source_id):
    m_path = manifest_path(source_id)
    if not os.path.isfile(m_path):
        print(f"No manifest found for '{source_id}' -- nothing to clean up.")
        return

    with open(m_path) as f:
        owned_classes = set(json.load(f))

    others = other_sources_manifests(source_id)

    removed, skipped = [], []
    for class_name in sorted(owned_classes):
        claimed_elsewhere = any(class_name in classes for classes in others.values())
        if claimed_elsewhere:
            skipped.append(class_name)
            continue
        class_path = os.path.join(REPO_ROOT, class_name)
        if os.path.isdir(class_path):
            shutil.rmtree(class_path)
        removed.append(class_name)

    for path in (m_path, failures_path(source_id)):
        if os.path.isfile(path):
            os.remove(path)

    print(f"Removed {len(removed)} class(es) for '{source_id}': {', '.join(removed) or '(none)'}")
    if skipped:
        print(f"Skipped {len(skipped)} class(es) still claimed by another source: {', '.join(skipped)}")


def main():
    if len(sys.argv) != 2:
        print("Usage: remove_source.py <source_id>", file=sys.stderr)
        sys.exit(1)
    remove_source(sys.argv[1])


if __name__ == "__main__":
    main()
