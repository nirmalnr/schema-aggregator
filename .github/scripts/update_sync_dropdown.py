#!/usr/bin/env python3
"""
Regenerates sync.yml's source_id dropdown to match the current sources.yaml,
without touching anything else in the file.

sync.yml is otherwise hand-curated (comments, workflow logic) -- round-
tripping it through a YAML parser risks reformatting or losing comments
elsewhere. Instead, the options list is wrapped in marker comments
(# BEGIN generated options / # END generated options) and only the text
between them is replaced, via plain string manipulation.
"""

import os
import re

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")
SYNC_WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "sync.yml")

BEGIN_MARKER = "        # BEGIN generated options"
END_MARKER = "        # END generated options"


def load_source_ids():
    with open(SOURCES_YAML) as f:
        data = yaml.safe_load(f) or {}
    return [s["id"] for s in data.get("sources", []) if "id" in s]


def build_options_block(ids):
    lines = [BEGIN_MARKER, "        options:", "          - all"]
    for source_id in ids:
        lines.append(f"          - {source_id}")
    lines.append(END_MARKER)
    return "\n".join(lines)


def main():
    ids = load_source_ids()

    with open(SYNC_WORKFLOW) as f:
        content = f.read()

    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    if not pattern.search(content):
        raise RuntimeError(
            f"Could not find the marker block ({BEGIN_MARKER} ... {END_MARKER}) in sync.yml"
        )

    new_content = pattern.sub(build_options_block(ids), content)

    if new_content == content:
        print("Dropdown already up to date, no change needed.")
        return

    with open(SYNC_WORKFLOW, "w") as f:
        f.write(new_content)
    print(f"Regenerated sync.yml dropdown with {len(ids)} source(s): {', '.join(ids)}")


if __name__ == "__main__":
    main()
