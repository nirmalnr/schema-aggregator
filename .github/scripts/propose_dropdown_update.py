#!/usr/bin/env python3
"""
Proposes a sync.yml dropdown update as its own small PR, rather than
committing it directly the way sources_changed.py commits everything else.

GITHUB_TOKEN can never push a commit that touches anything under
.github/workflows/ directly -- that's a hard platform restriction meant to
stop a workflow from self-escalating its own permissions, and no
`permissions:` block can grant around it. Opening a PR (which still needs
a human, or an approved auto-merge, to actually land it) is the standard
way anything automated proposes a workflow-file change -- the same
approach Dependabot etc. use.

Run from a clean checkout of main. If regeneration finds nothing to
change, this is a no-op.
"""

import json
import os
import subprocess

from update_sync_dropdown import regenerate

BRANCH = "update-sync-dropdown"


def existing_open_pr():
    result = subprocess.run(
        ["gh", "pr", "list", "--head", BRANCH, "--state", "open", "--json", "url"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    prs = json.loads(result.stdout or "[]")
    return prs[0]["url"] if prs else None


def main():
    changed = regenerate()
    if not changed:
        return

    already_open = existing_open_pr()

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email",
                     "github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "checkout", "-B", BRANCH], check=True)
    subprocess.run(["git", "add", ".github/workflows/sync.yml"], check=True)
    subprocess.run(["git", "commit", "-m", "Regenerate sync.yml dropdown from sources.yaml"], check=True)
    subprocess.run(["git", "push", "-u", "origin", BRANCH, "--force"], check=True)

    if already_open:
        print(f"Updated existing dropdown PR: {already_open}")
        return

    result = subprocess.run(
        ["gh", "pr", "create", "--title", "Regenerate sync.yml dropdown",
         "--body", "Automated: sync.yml's source_id dropdown no longer matches sources.yaml. "
                   "This only touches the marked options block.",
         "--head", BRANCH, "--base", "main"],
        check=True, capture_output=True, text=True,
    )
    print(f"Opened dropdown PR: {result.stdout.strip()}")


if __name__ == "__main__":
    main()
