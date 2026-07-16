#!/usr/bin/env python3
"""
Shared core for proposing a new schema source. Both the workflow_dispatch
wrapper (add-source-dispatch.yml) and the issue-form wrapper
(add-source-issue.yml) call this with the same four values -- everything
after collecting the input is identical regardless of which one triggered it.

Does the cheap, no-full-clone validation (source_id shape/uniqueness,
schema_path shape, and one lightweight GitHub API existence check for the
repo/ref/subpath) and, if everything passes, opens a PR adding the entry to
sources.yaml. Full content validation (does the schema actually have valid
classes) deliberately does NOT happen here -- that's validate_source_pr.py,
running as a required check on the PR this script opens, since it needs a
full clone and this step is meant to be the fast, no-PR-yet gate.

Reads SOURCE_ID, SCHEMA_PATH, DESCRIPTION, TAGS from the environment, plus
optional ISSUE_NUMBER (set by add-source-issue.yml only) to add a
"Closes #N" link so merging the PR auto-closes the originating issue.

On success: writes pr_url=<url> to $GITHUB_OUTPUT, exits 0.
On failure: writes error=<message> to $GITHUB_OUTPUT, exits 1 -- so the
dispatch workflow run just fails with a clear message, and the issue
wrapper can catch the failure (continue-on-error) and comment on the issue
instead, since there's no run log for that caller to check. Every git/gh
subprocess call and any other unexpected exception is funneled through
fail() at the top level too, so error= is never left blank -- found via a
real race: add-source-issue.yml can fire twice near-simultaneously for one
issue (opened + labeled events both firing at creation time), and an
uncaught CalledProcessError from a losing `git push --force` used to
produce an empty error message instead of a real one.
"""

import os
import re
import subprocess
import sys

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")

TREE_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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


def check_path_exists(owner, repo, ref, subpath):
    """One lightweight Contents API call -- confirms repo/ref/subpath all
    exist, without a full clone. Works for the subpath being a directory
    (returns a JSON array) or, less likely here, a file (a JSON object).

    Shells out to `gh api` rather than using urllib directly: it's already
    authenticated the same way the rest of these scripts are, and avoids
    urllib needing its own separately-configured CA trust store (a real,
    observed local-machine issue: urllib SSL cert verification can fail
    depending on how Python was installed, even though `gh`/`curl` on the
    same machine work fine)."""
    result = subprocess.run(
        ["gh", "api", "-X", "GET", f"repos/{owner}/{repo}/contents/{subpath}", "-f", f"ref={ref}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if "404" in result.stderr or "Not Found" in result.stderr:
        return False
    raise RuntimeError(result.stderr.strip())


def format_entry(source_id, schema_path, description, tags):
    """Manually formatted to match the existing hand-written style in
    sources.yaml, rather than round-tripping through yaml.dump (which would
    risk reformatting quoting/spacing inconsistently with the rest of the
    file)."""
    lines = [
        f"  - id: {source_id}",
        f'    schemaPath: "{schema_path}"',
    ]
    if description:
        escaped = description.replace('"', '\\"')
        lines.append(f'    description: "{escaped}"')
    if tags:
        tag_list = ", ".join(f'"{t}"' for t in tags)
        lines.append(f"    tags: [{tag_list}]")
    return "\n".join(lines) + "\n"


def existing_open_pr(branch):
    result = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    import json
    prs = json.loads(result.stdout or "[]")
    return prs[0]["url"] if prs else None


def main():
    source_id = os.environ.get("SOURCE_ID", "").strip()
    schema_path = os.environ.get("SCHEMA_PATH", "").strip()
    description = os.environ.get("DESCRIPTION", "").strip()
    tags_raw = os.environ.get("TAGS", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    if not source_id or not schema_path:
        fail("source_id and schema_path are both required.")

    if not SAFE_ID_RE.match(source_id):
        fail(f"source_id '{source_id}' must be lowercase letters, digits, and "
             f"hyphens only, starting with a letter or digit.")

    existing = load_sources()
    if any(s.get("id") == source_id for s in existing):
        fail(f"source_id '{source_id}' is already registered in sources.yaml.")

    m = TREE_URL_RE.match(schema_path)
    if not m:
        fail(f"schema_path '{schema_path}' doesn't match "
             f"https://github.com/<owner>/<repo>/tree/<ref>/<subpath>.")
    owner, repo, ref, subpath = m.groups()

    try:
        exists = check_path_exists(owner, repo, ref, subpath)
    except Exception as e:
        fail(f"Could not check {owner}/{repo}@{ref}:{subpath} -- {e}")
        return
    if not exists:
        fail(f"'{subpath}' not found in {owner}/{repo}@{ref} -- check the "
             f"repo, ref, and path are correct.")

    branch = f"add-source-{source_id}"

    already_open = existing_open_pr(branch)
    if already_open:
        succeed(already_open)
        return

    run = lambda *args: subprocess.run(args, check=True, capture_output=True, text=True)  # noqa: E731

    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com")
    run("git", "checkout", "-b", branch)

    with open(SOURCES_YAML, "a") as f:
        f.write("\n" + format_entry(source_id, schema_path, description, tags))

    run("git", "add", "sources.yaml")
    run("git", "commit", "-m", f"Add source: {source_id}")
    run("git", "push", "-u", "origin", branch, "--force")

    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    closes_line = f"\n\nCloses #{issue_number}" if issue_number else ""
    pr_body = (
        f"Proposes registering **{source_id}**.\n\n"
        f"- Schema path: {schema_path}\n"
        f"- Description: {description or '_none provided_'}\n"
        f"- Tags: {', '.join(tags) if tags else '_none_'}\n\n"
        f"A validation check will run shortly and comment with what would actually publish."
        f"{closes_line}"
    )
    result = run("gh", "pr", "create", "--title", f"Add source: {source_id}",
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
