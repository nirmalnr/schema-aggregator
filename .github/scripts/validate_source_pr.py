#!/usr/bin/env python3
"""
Required PR check for sources.yaml changes (validate-source-pr.yml).

Diffs sources.yaml between the PR's base and head to find newly-added (or
changed) source entries, clones each one fresh, and runs the same
schema_validator.py checks the sync workflow uses -- but here purely as a
preview: nothing is copied into the repo, this only reports what WOULD
happen.

Posts the breakdown as a PR comment. Exits non-zero (blocking merge, since
this runs as a required check) only if a newly-added source would publish
ZERO valid classes -- almost always a mistake (wrong subpath, wrong ref).
A source with SOME valid and some invalid classes is not blocking, since
partial validity is tolerated everywhere else in this system; it's only
reported so the reviewer can make an informed call.

Env vars: BASE_SHA, HEAD_SHA, PR_NUMBER, GH_TOKEN.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

from schema_validator import validate_class_dir

TREE_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")


def sources_at(ref):
    result = subprocess.run(["git", "show", f"{ref}:sources.yaml"], capture_output=True, text=True)
    if result.returncode != 0:
        return {}
    data = yaml.safe_load(result.stdout) or {}
    return {s["id"]: s for s in data.get("sources", []) if "id" in s}


def find_changed_sources(base_sha, head_sha):
    before = sources_at(base_sha)
    after = sources_at(head_sha)
    changed = []
    for source_id, entry in after.items():
        if source_id not in before or before[source_id] != entry:
            changed.append(entry)
    return changed


def validate_source(entry):
    schema_path = entry["schemaPath"]
    m = TREE_URL_RE.match(schema_path)
    if not m:
        return {"id": entry["id"], "error": f"malformed schemaPath: {schema_path}", "classes": []}
    owner, repo, ref, subpath = m.groups()

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = os.path.join(tmp, "clone")
        result = subprocess.run(
            ["git", "clone", "--depth=1", "--branch", ref,
             f"https://github.com/{owner}/{repo}.git", clone_dir],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"id": entry["id"], "error": f"could not clone {owner}/{repo}@{ref}", "classes": []}

        src_dir = os.path.join(clone_dir, subpath)
        if not os.path.isdir(src_dir):
            return {"id": entry["id"], "error": f"'{subpath}' not found in {owner}/{repo}@{ref}", "classes": []}

        classes = []
        for entry_name in sorted(os.listdir(src_dir)):
            entry_path = os.path.join(src_dir, entry_name)
            if not os.path.isdir(entry_path):
                continue
            class_issues, valid_versions, version_issues = validate_class_dir(entry_path)
            issue_count = len(class_issues) + sum(len(v) for v in version_issues.values())
            classes.append({
                "name": entry_name,
                "valid_versions": len(valid_versions),
                "issue_count": issue_count,
            })
        return {"id": entry["id"], "error": None, "classes": classes}


def build_comment(results):
    lines = ["## Source validation preview\n"]
    any_blocking = False

    for r in results:
        lines.append(f"### `{r['id']}`\n")
        if r["error"]:
            lines.append(f"**Blocking:** {r['error']}\n")
            any_blocking = True
            continue

        total = len(r["classes"])
        publishable = sum(1 for c in r["classes"] if c["valid_versions"] > 0)
        with_issues = sum(1 for c in r["classes"] if c["issue_count"] > 0)

        if total == 0 or publishable == 0:
            lines.append(f"**Blocking: zero of {total} classes would publish anything.** "
                          f"This is almost always a wrong subpath or ref -- please double check.\n")
            any_blocking = True
        else:
            lines.append(f"{publishable} of {total} classes would publish "
                          f"({with_issues} have at least one validation issue).\n")
            if with_issues:
                lines.append("| Class | Valid versions | Issues found |")
                lines.append("|---|---|---|")
                for c in r["classes"]:
                    if c["issue_count"] > 0:
                        lines.append(f"| {c['name']} | {c['valid_versions']} | {c['issue_count']} |")
                lines.append("")

    return "\n".join(lines), any_blocking


def main():
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]
    pr_number = os.environ["PR_NUMBER"]

    changed = find_changed_sources(base_sha, head_sha)
    if not changed:
        print("No source entries added or changed in this PR -- nothing to validate.")
        return

    results = [validate_source(entry) for entry in changed]
    comment, any_blocking = build_comment(results)

    subprocess.run(["gh", "pr", "comment", pr_number, "--body", comment], check=True)

    if any_blocking:
        print("BLOCKING: at least one proposed source would publish nothing.", file=sys.stderr)
        sys.exit(1)

    print("All proposed sources have at least some publishable content.")


if __name__ == "__main__":
    main()
