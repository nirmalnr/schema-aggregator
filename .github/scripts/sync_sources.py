#!/usr/bin/env python3
"""
Pull-and-flatten sync for schema-aggregator.

Reads sources.yaml, and for each matching source:
  - shallow-clones its GitHub tree URL at the tracked ref
  - validates each class/version found (schema_validator.validate_class_dir)
  - copies only versions that pass validation into the repo root, flattened
    (no per-source subfolder), with the leading "v" stripped from the
    destination version-directory name (source's "v2.0" -> our "2.0")
  - detects classes that no longer exist upstream (via a per-source manifest
    committed at .sync/manifest-<source_id>.json) and removes them

A version/class that fails validation is left untouched this run (whatever
was there from a prior successful sync stays, nothing broken is published).
A class that's genuinely gone upstream is removed and reported, not just
left to rot.

Controlled by the SOURCE_ID env var: "all" (default) or a specific id.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

from schema_validator import validate_class_dir

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")
MANIFEST_DIR = os.path.join(REPO_ROOT, ".sync")

TREE_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")
VERSION_PREFIX_RE = re.compile(r"^v(\d.*)$")

all_issues = []      # dicts: source_id, class_name, version, code, message
all_deletions = []   # dicts: source_id, class_name


# ── sources.yaml / manifest helpers ───────────────────────────────────────

def load_sources():
    with open(SOURCES_YAML) as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def parse_tree_url(url):
    m = TREE_URL_RE.search(url)
    if not m:
        raise ValueError(f"Could not parse GitHub tree URL: {url}")
    return m.groups()  # owner, repo, ref, subpath


def normalize_version(name):
    m = VERSION_PREFIX_RE.match(name)
    return m.group(1) if m else name


def manifest_path(source_id):
    return os.path.join(MANIFEST_DIR, f"manifest-{source_id}.json")


def load_manifest(source_id):
    path = manifest_path(source_id)
    if not os.path.isfile(path):
        return set()
    with open(path) as f:
        return set(json.load(f))


def write_manifest(source_id, class_names):
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    with open(manifest_path(source_id), "w") as f:
        json.dump(sorted(class_names), f, indent=2)
        f.write("\n")


def failures_path(source_id):
    return os.path.join(MANIFEST_DIR, f"failures-{source_id}.json")


def write_source_failures(source_id, issues):
    """
    Persist this source's CURRENT validation issues, replacing whatever was
    recorded for it last time. This is what makes the tracking issue reflect
    the true state of the whole registry even when a run only touches one
    source: a targeted run updates only its own source's file, but the
    aggregate report is always built from every source's file, not just the
    one(s) touched this run.
    """
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    path = failures_path(source_id)
    if issues:
        with open(path, "w") as f:
            json.dump(issues, f, indent=2)
            f.write("\n")
    elif os.path.isfile(path):
        os.remove(path)  # clean source -> no failures file needed for it


def aggregate_all_failures():
    """
    The current known validation state across every source that has ever
    been synced, not just the source(s) touched this run. This is what the
    tracking issue is built from, so a clean targeted run never wipes out
    or closes over another source's still-real failures.
    """
    if not os.path.isdir(MANIFEST_DIR):
        return []
    aggregate = []
    for fname in sorted(os.listdir(MANIFEST_DIR)):
        if not (fname.startswith("failures-") and fname.endswith(".json")):
            continue
        with open(os.path.join(MANIFEST_DIR, fname)) as f:
            aggregate.extend(json.load(f))
    return aggregate


# ── reporting ──────────────────────────────────────────────────────────────

def record_issue(source_id, class_name, version, code, message):
    issue = {
        "source_id": source_id, "class_name": class_name,
        "version": version, "code": code, "message": message,
    }
    all_issues.append(issue)
    path = f"{class_name}/{version}" if version else class_name
    print(f"::error file={path}::[{source_id}] [{code}] {message}")
    return issue


def record_deletion(source_id, class_name):
    all_deletions.append({"source_id": source_id, "class_name": class_name})
    print(f"::warning file={class_name}::[{source_id}] [removed] class no longer exists upstream")


def write_reports():
    current_failures = aggregate_all_failures()

    lines = []
    if all_deletions:
        lines.append("### Removed this run (no longer present upstream)\n")
        lines.append("| Source | Class |")
        lines.append("|---|---|")
        for d in all_deletions:
            lines.append(f"| {d['source_id']} | {d['class_name']} |")
        lines.append("")
    if current_failures:
        lines.append("### Validation issues (skipped, not published)\n")
        lines.append("_Reflects the current state across every synced source, not just this run._\n")
        lines.append("| Source | Class | Version | Issue |")
        lines.append("|---|---|---|---|")
        for i in current_failures:
            lines.append(
                f"| {i['source_id']} | {i['class_name']} | {i['version'] or '-'} | "
                f"`{i['code']}`: {i['message']} |"
            )
        lines.append("")

    report = "\n".join(lines) if lines else (
        "All sources passed validation, no upstream deletions detected.\n"
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write("## Schema sync report\n\n")
            f.write(report)

    failures_report_path = os.environ.get("VALIDATION_REPORT_PATH", "/tmp/validation-report.md")
    with open(failures_report_path, "w") as f:
        f.write(report)

    # has_failures gates the tracking issue: true if ANY source currently has
    # a known validation problem (aggregate, not just this run), or this run
    # found a deletion worth a one-time callout.
    has_failures = "true" if (current_failures or all_deletions) else "false"
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"has_failures={has_failures}\n")

    print(f"\nhas_failures={has_failures}")
    if all_issues:
        print(f"{len(all_issues)} validation issue(s) found this run.")
    if current_failures:
        print(f"{len(current_failures)} validation issue(s) currently known across all sources.")
    if all_deletions:
        print(f"{len(all_deletions)} class(es) removed (no longer upstream).")


# ── core sync ────────────────────────────────────────────────────────────

def sync_one(source):
    source_id = source["id"]
    schema_path = source["schemaPath"]
    owner, repo, ref, subpath = parse_tree_url(schema_path)
    print(f"--- Syncing {source_id} ({owner}/{repo}@{ref}:{subpath}) ---")

    source_issues = []  # this source's CURRENT issues, replaces its failures file wholesale

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = os.path.join(tmp, "clone")
        try:
            subprocess.run(
                [
                    "git", "clone", "--depth=1", "--branch", ref,
                    f"https://github.com/{owner}/{repo}.git", clone_dir,
                ],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            issue = record_issue(source_id, "(source)", None, "clone-failed",
                                  f"could not clone {owner}/{repo}@{ref}: {e.stderr.strip()}")
            source_issues.append(issue)
            write_source_failures(source_id, source_issues)
            return

        src_dir = os.path.join(clone_dir, subpath)
        if not os.path.isdir(src_dir):
            issue = record_issue(source_id, "(source)", None, "path-not-found",
                                  f"'{subpath}' not found in {owner}/{repo}@{ref}")
            source_issues.append(issue)
            write_source_failures(source_id, source_issues)
            return

        current_classes = set()
        copied_versions = 0

        for entry in sorted(os.listdir(src_dir)):
            entry_path = os.path.join(src_dir, entry)
            if not os.path.isdir(entry_path):
                continue  # skip loose root-level files (schema-root context.jsonld etc.)

            current_classes.add(entry)

            class_issues, valid_versions, version_issues = validate_class_dir(entry_path)
            for code, message in class_issues:
                source_issues.append(record_issue(source_id, entry, None, code, message))
            for version_name, issues in version_issues.items():
                for code, message in issues:
                    source_issues.append(record_issue(source_id, entry, version_name, code, message))

            if not valid_versions:
                continue  # nothing valid to publish for this class this run

            class_dest = os.path.join(REPO_ROOT, entry)
            os.makedirs(class_dest, exist_ok=True)

            readme_src = os.path.join(entry_path, "README.md")
            if os.path.isfile(readme_src):
                shutil.copy2(readme_src, os.path.join(class_dest, "README.md"))

            for version_name in valid_versions:
                normalized = normalize_version(version_name)
                dest_version_path = os.path.join(class_dest, normalized)

                # migration: drop an old v-prefixed sibling left over from before normalization
                if version_name != normalized:
                    old_prefixed_path = os.path.join(class_dest, version_name)
                    if os.path.isdir(old_prefixed_path):
                        shutil.rmtree(old_prefixed_path)

                if os.path.exists(dest_version_path):
                    shutil.rmtree(dest_version_path)
                shutil.copytree(os.path.join(entry_path, version_name), dest_version_path)
                copied_versions += 1

            print(f"  copied {entry}/ ({len(valid_versions)} version(s))")

        print(f"  {copied_versions} version(s) synced from {source_id}")

        # Deletion detection: anything in the previous manifest but absent now
        previous_classes = load_manifest(source_id)
        deleted = previous_classes - current_classes
        for class_name in sorted(deleted):
            class_path = os.path.join(REPO_ROOT, class_name)
            if os.path.isdir(class_path):
                shutil.rmtree(class_path)
            record_deletion(source_id, class_name)

        write_manifest(source_id, current_classes)
        write_source_failures(source_id, source_issues)


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

    write_reports()


if __name__ == "__main__":
    main()
