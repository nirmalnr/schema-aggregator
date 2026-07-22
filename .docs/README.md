# schema-aggregator

## Overview

`schema-aggregator` pulls schema artifacts -- `context.jsonld`, `vocab.jsonld`, `attributes.yaml`, and related files -- from multiple upstream GitHub repositories, validates them, and publishes the merged result as a flat `<Term>/<Version>/<file>` tree at the root of this repository. Publishing happens straight from git: there is no build step and no application server standing between a commit landing on `main` and that content being available.

## Motivation

This repo is a GitHub-native replacement for an older pipeline built around an admin application and a VM: a human triggered syncs through a UI, the app cloned each source, validated it, and wrote the result to local disk that a separate server then read from. That design had a single point of failure (one VM, one disk, no redundancy) and kept governance -- who can register a source, who approves a sync -- inside custom application code rather than GitHub's own permission model.

Here, the same responsibilities are handled by GitHub Actions and pull requests: registering a source is a reviewable PR, syncing is a workflow run with a visible log, and access control is repo permissions rather than an app's role system. This repo is one piece of a broader move to serve schema content off GitHub-backed infrastructure generally, described separately in the schema-serving migration proposal.

## Architecture

### Source Registry

Every upstream source is one entry in `sources.yaml`, at repo root:

| Field | Meaning |
|---|---|
| `id` | Stable, explicit identifier for the source. Not derived from the repo/path, so two sources from the same upstream repo never collide over an id. |
| `schemaPath` | A GitHub tree URL pointing at the folder to pull from, e.g. `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>`. |
| `description` | Human-readable summary. |
| `tags` | Optional domain tags applied to everything pulled from this source. |

A source's position in this file also determines its priority -- see Collision Resolution below.

### Sync Pipeline

A sync clones each source, walks its class directories, and validates every version directory it finds (see Validation). Failure isolation happens at the version level, not the class or source level: a single broken version doesn't stop the rest of that class's versions from publishing, and a broken class doesn't stop the rest of that source. A source with some invalid content still publishes everything that is valid.

### Collision Resolution

If two sources both provide a class with the same name, the source listed **earlier** in `sources.yaml` wins. The later source's class is skipped entirely and logged as an error rather than silently dropped -- its own content is never deleted or overwritten, since the position of a source in the file can change independently of what it happens to sync in any given run.

### Deletion Handling

If a class or version disappears from a source's upstream repo, it is removed from this repo on the next sync of that source. The one exception is a class that had already lost a naming collision to another source: since that class was never this source's content to begin with, this source's own sync never touches it.

### Status Reporting

A single tracking Issue reflects the current state of every validation issue across every source, rebuilt from the full aggregate state each time it updates -- not just whatever happened to run most recently. This means syncing one clean source never masks failures reported by another, and syncing one already-broken source never suppresses issues fixed by a previous run.

## Validation

Validation is grouped below by *when* it runs, since some checks only make sense in the context of a specific action (proposing a source, for instance) rather than as a standalone list.

### At Sync Time

Runs for every source, on every sync.

**Structural checks, class level:**
- `missing-readme` -- the class directory has no `README.md`. Non-blocking: the class still publishes.
- `no-versions` -- the class directory contains no version subdirectories at all.

**Structural checks, version level** (checked independently for every version directory):
- `bad-version-name` -- the directory name doesn't match `vX[.Y[.Z]]`.
- `missing-file` -- one of the four required files is absent: `attributes.yaml`, `context.jsonld`, `vocab.jsonld`, `README.md`.
- `invalid-yaml` -- `attributes.yaml` fails to parse.

A version with any of these issues is skipped; its sibling versions still publish.

**Collision check:**
- `owned-by-other-source` -- this class name is already owned by a source listed earlier in `sources.yaml`. The class is skipped for this source.

### When Proposing a New Source

**Pre-submission** -- runs before any pull request is opened, without cloning anything:
- `source_id` and `schema_path` are both required.
- `source_id` must be lowercase letters, digits, and hyphens only.
- `source_id` must not already be registered.
- `schema_path` must match the `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>` shape.
- The referenced repo, ref, and subpath must actually exist.

Any failure here means no pull request is created; the error is reported directly to wherever the proposal was made.

**Pull request check** -- runs once the proposal's pull request exists. Does a full clone of the proposed source and runs the same structural checks listed under *At Sync Time* against every class it finds. Blocks the merge only if the proposed source would publish zero valid classes -- almost always a sign of a wrong ref or subpath. If at least one class would publish, the check passes and instead comments the full breakdown of what would and wouldn't be included, so a reviewer can make an informed call before merging.

### When Proposing a Source Removal

- `source_id` is required.
- It must currently be registered in `sources.yaml`.
- Its exact entry must be found in the file, so it can be removed cleanly.

## Usage

### Running a Sync

Trigger the sync workflow manually, choosing either every source or one specific source by id.

### Adding a Source

Propose a new entry either by triggering the add-source workflow directly, or by opening an issue using the "Add source" issue form -- both collect the same information and go through the same validation described above. Once merged, the new source is synced automatically.

### Removing a Source

Mirrors adding a source: trigger the remove-source workflow, or open an issue using the "Remove source" issue form. Once merged, that source's published content is cleaned up automatically.

### Checking Validation Status

The tracking Issue always reflects current validation state across all sources. A specific workflow run's log shows what happened during that run alone.

## Hosting

### Serving Model

This repo is published via GitHub Pages from the `main` branch root, using the legacy (Jekyll) build. Content is available at clean `<term>/<version>/<file>` URLs matching the repo's own layout.

### Excluded Paths

`.sync/`, `.github/`, and `.docs/` are not publicly reachable through Pages today, but only as a side effect of Jekyll's default build silently excluding dot-prefixed paths -- no `.nojekyll` file is present. This is not a deliberate access control and it will stop working if hosting ever moves to Cloudflare Pages, or if `.nojekyll` is added here for true zero-build passthrough. Revisit how these paths stay unpublished before either of those changes.
