#!/usr/bin/env python3
"""
Structural validation for schema-aggregator sync (POC scope).

Mirrors the structural/parseability checks the schema.beckn.io admin app's
validator already does, deliberately NOT including any content-shape
enforcement on attributes.yaml (e.g. requiring an OpenAPI envelope) — that's
a separate, bigger decision left for later.

Failure isolation is per VERSION directory, not per class or per source:
a class with one broken version and three good ones still publishes the
three good ones.
"""

import os
import re

import yaml

VERSION_DIR_RE = re.compile(r"^v\d+(\.\d+){0,2}$")
REQUIRED_VERSION_FILES = ["attributes.yaml", "context.jsonld", "vocab.jsonld", "README.md"]


def _clean_yaml_error(e):
    """
    Format a yaml.YAMLError without the absolute temp-clone path PyYAML embeds
    in str(e) (e.g. "/tmp/tmpXXXXXX/clone/schema/Foo/v1.0/attributes.yaml") —
    that path is meaningless to a human reading a validation report; only the
    problem description and location within the file are useful.
    """
    problem = getattr(e, "problem", None)
    mark = getattr(e, "problem_mark", None)
    if problem and mark is not None:
        return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"
    return str(e).splitlines()[0]


def validate_version_dir(version_path):
    """Return a list of (code, message) issues for one version directory. Empty = valid."""
    issues = []
    version_name = os.path.basename(version_path)

    if not VERSION_DIR_RE.match(version_name):
        issues.append(("bad-version-name", f"'{version_name}' doesn't match vX[.Y[.Z]]"))

    for fname in REQUIRED_VERSION_FILES:
        if not os.path.isfile(os.path.join(version_path, fname)):
            issues.append(("missing-file", f"missing required file '{fname}'"))

    attrs_path = os.path.join(version_path, "attributes.yaml")
    if os.path.isfile(attrs_path):
        try:
            with open(attrs_path) as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            issues.append(("invalid-yaml", f"attributes.yaml failed to parse: {_clean_yaml_error(e)}"))

    return issues


def validate_class_dir(class_path):
    """
    Validate a class directory.

    Returns (class_issues, valid_versions, version_issues):
      class_issues   : list of (code, message) for the class itself (e.g. missing README)
      valid_versions : list of version directory names that passed validation
      version_issues : dict version_name -> list of (code, message)
    """
    class_issues = []
    if not os.path.isfile(os.path.join(class_path, "README.md")):
        class_issues.append(("missing-readme", "class is missing README.md"))

    version_issues = {}
    valid_versions = []
    found_any_version_dir = False

    for entry in sorted(os.listdir(class_path)):
        entry_path = os.path.join(class_path, entry)
        if not os.path.isdir(entry_path):
            continue
        found_any_version_dir = True
        issues = validate_version_dir(entry_path)
        if issues:
            version_issues[entry] = issues
        else:
            valid_versions.append(entry)

    if not found_any_version_dir:
        class_issues.append(("no-versions", "class has no version directories"))

    return class_issues, valid_versions, version_issues
