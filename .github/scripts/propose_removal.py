#!/usr/bin/env python3
"""
Shared core for proposing a source's removal. Mirrors propose_source.py's
structure and hard-won fixes (captured subprocess output, top-level
exception handling so error= is never blank, optional ISSUE_NUMBER for a
"Closes #N" link) -- the only real difference is there's no new information
to validate here beyond "does this source_id actually exist."

Removing the entry itself doesn't need its own validation check on the PR
(validate-source-pr.yml only looks at added/changed entries, so a pure
removal is invisible to it and correctly skipped) -- the actual content
cleanup (deleting the classes this source owned, its manifest, its
failures file) already happens on merge via sources-changed.yml +
remove_source.py, unchanged and reused as-is regardless of how the
sources.yaml PR was created.

Reads SOURCE_ID from the environment, plus optional ISSUE_NUMBER (set by
remove-source-issue.yml only).

On success: writes pr_url=<url> to $GITHUB_OUTPUT, exits 0.
On failure: writes error=<message> to $GITHUB_OUTPUT, exits 1.
"""

import json
import os
import re
import subprocess
import sys

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")


def fail(message):
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"error={message}\n")
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def succeed(pr_url):
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"pr_url={pr_url}\n")
    print(f"PR ready: {pr_url}")


def load_sources():
    if not os.path.isfile(SOURCES_YAML):
        return []
    with open(SOURCES_YAML) as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", [])


def remove_entry_text(source_id):
    """Removes the `  - id: <source_id>` block from sources.yaml's raw text,
    the same way the entry was appended as raw text in propose_source.py --
    keeps the rest of the file's hand-written formatting untouched rather
    than round-tripping through a YAML dumper."""
    with open(SOURCES_YAML) as f:
        content = f.read()

    pattern = re.compile(
        r"\n?  - id: " + re.escape(source_id) + r"\n(?:    .*\n)*"
    )
    new_content, count = pattern.subn("", content)
    if count == 0:
        return None
    with open(SOURCES_YAML, "w") as f:
        f.write(new_content)
    return new_content


def existing_open_pr(branch):
    result = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    prs = json.loads(result.stdout or "[]")
    return prs[0]["url"] if prs else None


def main():
    source_id = os.environ.get("SOURCE_ID", "").strip()
    if not source_id:
        fail("source_id is required.")

    existing = load_sources()
    if not any(s.get("id") == source_id for s in existing):
        fail(f"source_id '{source_id}' isn't currently registered in sources.yaml -- "
             f"nothing to remove.")

    branch = f"remove-source-{source_id}"

    already_open = existing_open_pr(branch)
    if already_open:
        succeed(already_open)
        return

    run = lambda *args: subprocess.run(args, check=True, capture_output=True, text=True)  # noqa: E731

    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com")
    run("git", "checkout", "-b", branch)

    if remove_entry_text(source_id) is None:
        fail(f"Could not find the '{source_id}' entry's exact text to remove -- "
             f"sources.yaml may be formatted differently than expected.")
        return

    run("git", "add", "sources.yaml")
    run("git", "commit", "-m", f"Remove source: {source_id}")
    run("git", "push", "-u", "origin", branch, "--force")

    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    closes_line = f"\n\nCloses #{issue_number}" if issue_number else ""
    pr_body = (
        f"Proposes removing **{source_id}** from `sources.yaml`.\n\n"
        f"On merge, `sources-changed.yml` will delete every class this source "
        f"owns (per its `.sync/manifest-{source_id}.json`), skipping any class "
        f"also claimed by another source, then remove its manifest and failures "
        f"files."
        f"{closes_line}"
    )
    result = run("gh", "pr", "create", "--title", f"Remove source: {source_id}",
                 "--body", pr_body, "--head", branch, "--base", "main")
    succeed(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        cmd = " ".join(e.cmd)
        fail(f"command failed ({cmd}): {stderr or f'exit code {e.returncode}'}")
    except Exception as e:
        fail(f"unexpected error: {e}")
