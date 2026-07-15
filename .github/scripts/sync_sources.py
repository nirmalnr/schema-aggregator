#!/usr/bin/env python3
"""
Pull-and-flatten sync for schema-aggregator (POC).

Reads sources.yaml, and for each matching source, shallow-clones its
GitHub tree URL at the tracked ref and copies each class directory found
under the schema subpath into the repo root, flattened (no per-source
subfolder). Root-level loose files in the source (e.g. a schema-root
context.jsonld/vocab.jsonld, README.md, INDEX.md) are intentionally
skipped — this POC only proves out per-term/version file serving.

Controlled by the SOURCE_ID env var: "all" (default) or a specific id.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")

TREE_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")


def load_sources():
    with open(SOURCES_YAML) as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def parse_tree_url(url):
    m = TREE_URL_RE.search(url)
    if not m:
        raise ValueError(f"Could not parse GitHub tree URL: {url}")
    owner, repo, ref, subpath = m.groups()
    return owner, repo, ref, subpath


def sync_one(source):
    source_id = source["id"]
    schema_path = source["schemaPath"]
    owner, repo, ref, subpath = parse_tree_url(schema_path)
    print(f"--- Syncing {source_id} ({owner}/{repo}@{ref}:{subpath}) ---")

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = os.path.join(tmp, "clone")
        subprocess.run(
            [
                "git", "clone", "--depth=1", "--branch", ref,
                f"https://github.com/{owner}/{repo}.git", clone_dir,
            ],
            check=True,
        )

        src_dir = os.path.join(clone_dir, subpath)
        if not os.path.isdir(src_dir):
            print(f"  WARNING: '{subpath}' not found in {owner}/{repo}@{ref}, skipping")
            return

        copied = 0
        for entry in sorted(os.listdir(src_dir)):
            entry_path = os.path.join(src_dir, entry)
            if not os.path.isdir(entry_path):
                continue  # skip loose root-level files (context.jsonld, README.md, etc.)

            dest_path = os.path.join(REPO_ROOT, entry)
            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)
            shutil.copytree(entry_path, dest_path)
            copied += 1
            print(f"  copied {entry}/")

        print(f"  {copied} class director{'y' if copied == 1 else 'ies'} synced from {source_id}")


def main():
    requested = os.environ.get("SOURCE_ID", "all")
    sources = load_sources()

    if requested != "all":
        sources = [s for s in sources if s["id"] == requested]
        if not sources:
            print(f"No source with id '{requested}' found in sources.yaml", file=sys.stderr)
            sys.exit(1)

    if not sources:
        print("No sources to sync.", file=sys.stderr)
        sys.exit(1)

    for source in sources:
        sync_one(source)


if __name__ == "__main__":
    main()
