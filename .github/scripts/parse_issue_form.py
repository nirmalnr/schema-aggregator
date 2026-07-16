#!/usr/bin/env python3
"""
Parses a GitHub Issue Form submission's rendered body back into field
values. GitHub renders each form field as a "### <Label>" heading followed
by the answer (or "_No response_" if left blank on an optional field).

Reads the issue body from the ISSUE_BODY env var. Writes source_id,
schema_path, description, tags to $GITHUB_OUTPUT.
"""

import os
import re

FIELDS = {
    "Source ID": "source_id",
    "Schema Path": "schema_path",
    "Description": "description",
    "Tags": "tags",
}


def parse(body):
    values = {}
    # Split on "### <heading>" markers, GitHub's issue-form rendering format.
    sections = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
    # sections = ['', 'Source ID', '\n\nfoo\n\n', 'Schema Path', '\n\nhttps://...\n\n', ...]
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        answer = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if answer == "_No response_":
            answer = ""
        key = FIELDS.get(heading)
        if key:
            values[key] = answer
    return values


def main():
    body = os.environ.get("ISSUE_BODY", "")
    values = parse(body)

    output_path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{field}={values.get(field, '')}" for field in FIELDS.values()]
    if output_path:
        with open(output_path, "a") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
