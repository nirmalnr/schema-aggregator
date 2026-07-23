#!/usr/bin/env python3
"""
Pull-and-flatten sync for schema-aggregator.

Reads sources.yaml, and for each matching source:
  - shallow-clones its GitHub tree URL at the tracked ref
  - skips any class already owned by an earlier-listed source (see
    "Cross-source collisions" below), reporting it as an issue
  - validates each remaining class/version found (schema_validator.validate_class_dir)
  - copies only versions that pass validation into the repo root, flattened
    (no per-source subfolder), with the leading "v" stripped from the
    destination version-directory name (source's "v2.0" -> our "2.0")
  - detects classes that no longer exist upstream (via a per-source manifest
    committed at .sync/manifest-<source_id>.json) and removes them

A version/class that fails validation is left untouched this run (whatever
was there from a prior successful sync stays, nothing broken is published).
A class that's genuinely gone upstream is removed and reported, not just
left to rot.

Cross-source collisions: if two different sources both have a class with
the same name, the source that appears FIRST in sources.yaml always wins,
regardless of which one happens to sync first in time. A later-listed
source's colliding class is never copied and is reported as an issue
("owned-by-other-source"), same reporting path as any other validation
failure. This is resolved by checking every earlier-listed source's
CURRENT manifest before touching each class -- which works correctly even
when syncing a single source in isolation, since manifests persist across
runs regardless of which source is being synced right now.

A class this source used to own but has just lost to a newly-higher-
priority source is dropped from this source's own manifest (it doesn't
own it anymore) but its on-disk content is deliberately NOT deleted --
the winning source's own sync is what's responsible for what ends up
there, and treating a lost collision as a plain deletion would risk
`rmtree`-ing the winner's freshly-published content out from under it.

On a full ("all") sync only: after every current source has synced, any
`.sync/manifest-<id>.json` whose id is no longer in sources.yaml is treated
as an orphan and cleaned up via remove_source.remove_source() -- the same
function sources-changed.yml calls for a source it sees disappear in a
single push's before/after diff. This makes "Sync sources" a genuine full
reconciliation against whatever sources.yaml currently says, regardless of
how a removal's cleanup was missed (a lost push race, a direct edit to
sources.yaml, anything) -- not just a re-pull of what's currently listed.

Controlled by the SOURCE_ID env var: "all" (default) or a specific id.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from schema_validator import validate_class_dir
from remove_source import remove_source
from sources_yaml import load_sources

REPO_ROOT = os.getcwd()
MANIFEST_DIR = os.path.join(REPO_ROOT, ".sync")

TREE_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")
VERSION_PREFIX_RE = re.compile(r"^v(\d.*)$")

all_issues = []      # dicts: source_id, class_name, version, code, message
all_deletions = []   # dicts: source_id, class_name


# ── manifest helpers ───────────────────────────────────────────────────────

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


def earlier_sources_owned_classes(source_id, ordered_source_ids):
    """
    Every class name currently claimed (per its persisted manifest) by a
    source that appears BEFORE source_id in sources.yaml. Only ever checks
    sources strictly earlier in the list -- a source never loses a class to
    one listed after it, no matter what order they happen to sync in.

    Returns {class_name: owning_source_id}, using the FIRST earlier owner
    found for a given class (in list order) if more than one earlier source
    happens to claim it.
    """
    owned = {}
    for other_id in ordered_source_ids:
        if other_id == source_id:
            break
        for class_name in load_manifest(other_id):
            owned.setdefault(class_name, other_id)
    return owned


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

def sync_one(source, ordered_source_ids):
    source_id = source["id"]
    schema_path = source["schemaPath"]
    owner, repo, ref, subpath = parse_tree_url(schema_path)
    print(f"--- Syncing {source_id} ({owner}/{repo}@{ref}:{subpath}) ---")

    blocked = earlier_sources_owned_classes(source_id, ordered_source_ids)
    blocked_this_run = set()  # classes found upstream this run but skipped due to collision

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

            if entry in blocked:
                owning_source_id = blocked[entry]
                issue = record_issue(
                    source_id, entry, None, "owned-by-other-source",
                    f"already provided by source '{owning_source_id}' (earlier in sources.yaml) -- not synced",
                )
                source_issues.append(issue)
                blocked_this_run.add(entry)
                continue  # not this source's to validate or publish

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

        # Deletion detection: anything in the previous manifest but absent now.
        # Explicitly excludes blocked_this_run -- a class this source just lost
        # to a higher-priority source is still physically present upstream, it
        # just isn't this source's to publish anymore. Treating that as a
        # deletion would rmtree the winning source's own content out from
        # under it (which may already be sitting there, or about to be).
        previous_classes = load_manifest(source_id)
        deleted = previous_classes - current_classes - blocked_this_run
        for class_name in sorted(deleted):
            class_path = os.path.join(REPO_ROOT, class_name)
            if os.path.isdir(class_path):
                shutil.rmtree(class_path)
            record_deletion(source_id, class_name)

        write_manifest(source_id, current_classes)
        write_source_failures(source_id, source_issues)


def reconcile_orphaned_manifests(ordered_source_ids):
    """
    Full-sync self-healing: a .sync/manifest-<id>.json whose id is no longer
    in sources.yaml means that source was removed at some point without its
    cleanup ever completing. Reuses remove_source() as-is -- same function
    sources-changed.yml calls, same "skip if claimed by another source's
    manifest" safety check -- rather than reimplementing the cleanup here.

    Runs after every current source has already synced above, so that
    safety check sees each current source's freshly written manifest, not
    a stale one from before this run.
    """
    if not os.path.isdir(MANIFEST_DIR):
        return
    current_ids = set(ordered_source_ids)
    for fname in sorted(os.listdir(MANIFEST_DIR)):
        if not (fname.startswith("manifest-") and fname.endswith(".json")):
            continue
        manifest_id = fname[len("manifest-"):-len(".json")]
        if manifest_id not in current_ids:
            print(f"--- '{manifest_id}' no longer in sources.yaml -- reconciling ---")
            remove_source(manifest_id)


def main():
    requested = os.environ.get("SOURCE_ID", "all")
    # Always load the FULL list, in file order, regardless of SOURCE_ID --
    # collision priority is relative to every registered source's position
    # in sources.yaml, not just whichever one(s) this run happens to touch.
    all_sources = load_sources()
    ordered_source_ids = [s["id"] for s in all_sources]

    if requested == "all":
        sources = all_sources
    else:
        sources = [s for s in all_sources if s["id"] == requested]
        if not sources:
            print(f"No source with id '{requested}' found in sources.yaml", file=sys.stderr)
            sys.exit(1)

    if not sources:
        print("No sources to sync.", file=sys.stderr)
        sys.exit(1)

    for source in sources:
        sync_one(source, ordered_source_ids)

    if requested == "all":
        reconcile_orphaned_manifests(ordered_source_ids)

    write_reports()


if __name__ == "__main__":
    main()
