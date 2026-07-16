#!/usr/bin/env python3
"""
Driver for sources-changed.yml. Diffs sources.yaml between the commit
before and after a push to main, and for each source id that changed:

  - newly added  -> runs sync_sources.py targeted at it (first content pull)
  - removed      -> runs remove_source.py to clean up its published content

The actual git commit/push happens in the calling workflow, same pattern
as sync.yml's own "commit if changed" step -- this script just leaves the
working tree in the right state. Does NOT touch sync.yml's dropdown --
see propose_dropdown_update.py for why that has to be a separate PR
rather than a direct commit.

Env vars: BASE_SHA, HEAD_SHA.
"""

import os
import subprocess
import sys

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")
SCRIPTS_DIR = os.path.join(REPO_ROOT, ".github", "scripts")


def source_ids_at(ref):
    result = subprocess.run(["git", "show", f"{ref}:sources.yaml"], capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    data = yaml.safe_load(result.stdout) or {}
    return {s["id"] for s in data.get("sources", []) if "id" in s}


def main():
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    before = source_ids_at(base_sha)
    after = source_ids_at(head_sha)

    added = sorted(after - before)
    removed = sorted(before - after)

    if not added and not removed:
        print("No source ids added or removed -- nothing to sync/clean up.")
    else:
        print(f"Added: {added or '(none)'}")
        print(f"Removed: {removed or '(none)'}")

    for source_id in added:
        print(f"\n=== First sync for newly added source: {source_id} ===")
        env = {**os.environ, "SOURCE_ID": source_id}
        subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "sync_sources.py")],
            env=env, check=True,
        )

    for source_id in removed:
        print(f"\n=== Cleaning up removed source: {source_id} ===")
        subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "remove_source.py"), source_id],
            check=True,
        )

    # NOTE: sync.yml's dropdown is deliberately NOT regenerated here.
    # GITHUB_TOKEN can never push a commit that touches .github/workflows/*
    # directly -- that's a hard platform restriction, not something any
    # `permissions:` block can grant. propose_dropdown_update.py handles it
    # separately, as its own PR (same pattern Dependabot etc. use for
    # workflow-file changes), run as a distinct step in sources-changed.yml.

    # Refresh the tracking-issue report from the current aggregate state on
    # disk (.sync/failures-*.json), so update_tracking_issue.sh has an
    # accurate answer regardless of whether this run added sources, removed
    # them, or both -- sync_sources.py's own has_failures output only covers
    # whichever single source it was last invoked for above, not the full
    # picture.
    sys.path.insert(0, SCRIPTS_DIR)
    import sync_sources  # noqa: E402
    sync_sources.write_reports()


if __name__ == "__main__":
    main()
