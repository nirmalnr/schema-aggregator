#!/usr/bin/env python3
"""
Shared load/write for sources.yaml -- used by propose_source.py,
propose_removal.py, and sync_sources.py, so there's exactly one place that
knows how to read and rewrite this file.

write_sources() does a real structural dump (load -> mutate the list ->
dump) instead of the raw-text append/regex-delete this used to be. That's
only safe because sources.yaml no longer carries a header comment --
PyYAML's load/dump round-trip has no concept of comments at all, so it
would otherwise silently delete one on every write. Full field
documentation lives in .docs/README.md instead.

The dump is configured to match the file's existing hand-written style
exactly (verified via diff against the real file before this was wired
in): list items indented under `sources:`, `schemaPath`/`description`/each
tag double-quoted, `tags` as a compact one-line flow list, one blank line
between entries, no line-wrapping on long descriptions. None of that is
needed for correctness -- only load_sources()/write_sources() and the
fixed FIELD_ORDER matter for that -- it's purely to avoid an unrelated
wall of formatting churn on every PR that touches this file.

Collision priority is entirely a function of *list order* under `sources:`,
which this never reorders: write_sources() writes exactly the list order
it's given, and PyYAML's `sort_keys` only ever affects the order of keys
*within* one entry's own fields, never the order of entries in the list.
"""

import os

import yaml

REPO_ROOT = os.getcwd()
SOURCES_YAML = os.path.join(REPO_ROOT, "sources.yaml")

FIELD_ORDER = ["id", "schemaPath", "description", "tags"]


class _QuotedStr(str):
    pass


class _FlowList(list):
    pass


class _SourcesDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        # PyYAML's default renders block sequences "indentless" relative to
        # their parent key (sources:\n- id: ...). Forcing indentless=False
        # here is what keeps the file's actual style (sources:\n  - id: ...).
        return super().increase_indent(flow, False)


_SourcesDumper.add_representer(
    _QuotedStr, lambda d, data: d.represent_scalar("tag:yaml.org,2002:str", data, style='"')
)
_SourcesDumper.add_representer(
    _FlowList, lambda d, data: d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)
)


def load_sources():
    if not os.path.isfile(SOURCES_YAML):
        return []
    with open(SOURCES_YAML) as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", [])


def _ordered_entry(entry):
    """Same entry, keys in the fixed id/schemaPath/description/tags order,
    with the quoting/flow-style wrappers applied -- a field only appears if
    it was already present on the entry (no forcing an empty description or
    tags onto an entry that never had one)."""
    out = {}
    for key in FIELD_ORDER:
        if key not in entry:
            continue
        if key in ("schemaPath", "description"):
            out[key] = _QuotedStr(entry[key])
        elif key == "tags":
            out[key] = _FlowList(_QuotedStr(t) for t in entry[key])
        else:
            out[key] = entry[key]
    return out


def write_sources(sources):
    """Write the given list of source entries, in the exact order given --
    callers control ordering (append to the end for an add, filter for a
    remove); this never reorders anything itself."""
    ordered = [_ordered_entry(s) for s in sources]
    text = yaml.dump(
        {"sources": ordered},
        Dumper=_SourcesDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1000,
    )

    lines = text.split("\n")
    out_lines = []
    seen_first_entry = False
    for line in lines:
        if line.startswith("  - id:"):
            if seen_first_entry:
                out_lines.append("")
            seen_first_entry = True
        out_lines.append(line)

    with open(SOURCES_YAML, "w") as f:
        f.write("\n".join(out_lines))
