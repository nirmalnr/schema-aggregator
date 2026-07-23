# schema-aggregator

## Overview

`schema-aggregator` pulls schema artifacts -- `context.jsonld`, `vocab.jsonld`, `attributes.yaml`, and related files -- from multiple upstream GitHub repositories, validates them, and publishes the merged result as a flat `<Schema>/<Version>/<file>` tree at the root of this repository. It holds Beckn's extended schemas: domain-specific schema packs that extend the core protocol, as distinct from the core data model itself, which lives in `protocol-specifications-v2`.

Publishing happens by pushing directly to this repository -- there is no admin application, sync server, or separate deployment pipeline standing between a merged change and that content going live. GitHub's own Pages build still has to run before a change is publicly reachable; see Hosting below for what that actually involves.

## Motivation

This repo is a GitHub-native replacement for an older pipeline built around an admin application and a VM: a human triggered syncs through a UI, the app cloned each source, validated it, and wrote the result to local disk that a separate server then read from directly. That design had a single point of failure -- one VM, one disk, no redundancy -- and kept governance, such as who can register a source or approve a sync, inside custom application code rather than GitHub's own permission model.

Here, the same responsibilities are handled by GitHub Actions and pull requests: registering a source is a reviewable PR, syncing is a workflow run with a visible log, and access control is repo permissions rather than an app's role system.

More broadly, this replaces disk reads off a single VM with serving from a CDN-backed origin: today that means GitHub Pages serving this repository directly, rather than an application reading from a local clone on disk. The durability and scale properties come from that origin, not from any code in this repo.

## Architecture

### Source Registry

Every upstream source is one entry in `sources.yaml`, at repo root:

| Field | Meaning |
|---|---|
| `id` | Derived automatically from the source's own `(owner, repo, ref, subpath)` -- `owner_repo_ref_subpath`, lowercased, `_`-joined. Nobody types this; re-proposing the exact same repo/branch/folder always derives the same id, so it's caught as an ordinary duplicate rather than silently registered twice. |
| `schemaPath` | A GitHub tree URL pointing at the folder to pull from, e.g. `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>`. |
| `description` | Human-readable summary. |
| `tags` | Optional domain tags applied to everything pulled from this source. |

A source's position in this file also determines its priority -- see Collision Resolution below.

### Sync Pipeline

A sync clones each source, walks the schemas it contains, and validates every schema pack it finds (see Validation). Failure isolation happens at the schema-pack level, not the schema or source level: a single broken schema pack doesn't stop the rest of that schema's packs from publishing, and a broken schema doesn't stop the rest of that source. A source with some invalid content still publishes everything that is valid.

### Collision Resolution

If two sources both provide a schema with the same name, the source listed **earlier** in `sources.yaml` wins. The later source's schema is skipped entirely and logged as an error rather than silently dropped -- its own content is never deleted or overwritten, since the position of a source in the file can change independently of what it happens to sync in any given run.

### Deletion Handling

If a schema or schema pack disappears from a source's upstream repo, it is removed from this repo on the next sync of that source. The one exception is a schema that had already lost a naming collision to another source: since that schema was never this source's content to begin with, this source's own sync never touches it.

### Status Reporting

A single tracking Issue reflects the current state of every validation issue across every source, rebuilt from the full aggregate state each time it updates -- not just whatever happened to run most recently. This means syncing one clean source never masks failures reported by another, and syncing one already-broken source never suppresses issues fixed by a previous run.

## Validation

### At Sync Time

Runs for every source, on every sync.

**Structural checks, schema level:**
- `missing-readme` -- the schema has no `README.md`. Non-blocking: the schema still publishes.
- `no-versions` -- the schema has no schema-pack directories at all.

**Structural checks, schema-pack level** (checked independently for every schema pack):
- `bad-version-name` -- the directory name doesn't match `vX[.Y[.Z]]`.
- `missing-file` -- one of the four required files is absent: `attributes.yaml`, `context.jsonld`, `vocab.jsonld`, `README.md`.
- `invalid-yaml` -- `attributes.yaml` fails to parse.

A schema pack with any of these issues is skipped; its sibling packs still publish.

**Collision check:**
- `owned-by-other-source` -- this schema name is already owned by a source listed earlier in `sources.yaml`. The schema is skipped for this source.

### When Proposing a New Source

**Pre-submission** -- runs before any pull request is opened, without cloning anything. The only input is `schema_path` (plus optional description/tags); there's no id to supply:
- `schema_path` is required.
- `schema_path` must match the `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>` shape.
- The referenced repo, ref, and subpath must actually exist.
- The id derived from that `(owner, repo, ref, subpath)` must not already be registered -- this is what actually catches a resubmission of the same repo/branch/folder, since the id is a pure function of those four values.

Any failure here means no pull request is created; the error is reported directly to wherever the proposal was made.

**Pull request check** -- runs once the proposal's pull request exists. Does a full clone of the proposed source and runs the same structural checks listed under *At Sync Time* against every schema it finds. Blocks the merge only if the proposed source would publish zero valid schemas -- almost always a sign of a wrong ref or subpath. If at least one schema would publish, the check passes and instead comments the full breakdown of what would and wouldn't be included, so a reviewer can make an informed call before merging.

### When Proposing a Source Removal

- `source_id` is required.
- It must currently be registered in `sources.yaml` -- checked structurally, by parsing the file and looking for a matching `id`.
- Separately, that entry's raw text must be found in `sources.yaml` in the expected hand-written shape (a `  - id: <id>` line followed by its indented fields). Removal deletes that literal text rather than re-serializing the whole file through a YAML dumper, to avoid reformatting the rest of the file or losing comments -- the same reasoning `propose_source.py` uses when adding an entry. This is a genuinely separate check from the one above: it can fail even when the id is registered, if `sources.yaml` was ever hand-edited into a differently-shaped (but still valid) YAML -- different indentation, an inline/flow-style entry, reordered fields -- since the parser would still find the id, but the text-matching removal wouldn't recognize that block's shape.

## Usage

Workflows in the Actions tab are named so the two groups are obvious at a glance: a numbered `(manual trigger)` workflow is one you run yourself; an unnumbered `(automatic...)` workflow runs itself and only has logs to read, never a button to click.

### Adding a Source

Two ways in, same validation either way (see Validation above), both ending in a PR that still needs a human to merge it.

**Via GitHub Issue** (no write access needed):
1. **Issues** -> **New issue** -> the **"Add a schema source"** template.
2. Fill in **Schema Path** (required), **Description** and **Tags** (optional). There's no id field to fill in -- it's derived automatically.
3. Submit. `Add source (automatic, via Issue)` picks it up within moments: on success, the issue's title updates from the template's placeholder to the derived source id, and a comment links the opened PR. On failure, the comment explains what to fix -- edit the issue with corrected details and it retries automatically.

**Via the Actions tab** (repo write access required):
1. Go to **Actions** -> **`1 Add source (manual trigger)`** -> **Run workflow**.
2. Fill in:
   - **schema_path** (required) -- a GitHub tree URL, e.g. `https://github.com/<owner>/<repo>/tree/<ref>/<subpath>`.
   - **description** (optional).
   - **tags** (optional, comma-separated).
3. Run it. The run's log either prints the opened PR's URL, or exactly what to fix (bad path shape, path doesn't exist, already registered) with no PR created.

**After the PR opens** (either path): `Validate proposed source (automatic)` runs as a required check and comments the breakdown -- how many schemas would publish, and any issues found. It only blocks the merge if zero schemas would publish; otherwise it's informational. Merge the PR once it looks right, same as any other PR -- `Sources changed (automatic)` picks up from there and syncs the new source in.

### Removing a Source

Mirrors adding a source.

**Via GitHub Issue**:
1. **Issues** -> **New issue** -> the **"Remove a schema source"** template.
2. Enter **Source ID** (must match exactly).
3. Submit. Here the title updates immediately (the id is something you typed, not derived), and `Remove source (automatic, via Issue)` handles the rest the same way as the add path.

**Via the Actions tab**:
1. **Actions** -> **`2 Remove source (manual trigger)`** -> **Run workflow**.
2. Enter **source_id** -- must exactly match an id currently in `sources.yaml` (check the Source Registry table above, or the tracking Issue, if unsure of the exact string).
3. Run it. Same success/failure reporting as Add Source.

**After the PR opens**: no PR-time check runs for a pure removal -- there's nothing new to validate, only an entry disappearing. Merge it directly; `Sources changed (automatic)` then deletes everything that source owned.

### Running a Sync

1. **Actions** -> **`3 Sync sources (manual trigger)`** -> **Run workflow**.
2. **source_id**: leave as `all` to sync every registered source, or enter one specific id to sync just that one.
3. Run it.

A full (`all`) run is also a complete reconciliation against whatever `sources.yaml` currently says -- not just a re-pull of what's listed, but a cleanup of anything left behind by a source that's no longer registered. It's the right thing to run any time something seems out of sync, regardless of why.

### Checking Validation Status

The tracking Issue always reflects current validation state across all sources. A specific workflow run's log shows what happened during that run alone.

## Hosting

### Serving Model

This repo is published via GitHub Pages from the `main` branch root, using the legacy (Jekyll) build. Each push triggers a fresh build -- typically under a minute -- after which the change is live at clean `<schema>/<version>/<file>` URLs matching the repo's own layout.

### Excluded Paths

`.sync/`, `.github/`, and `.docs/` are not publicly reachable through Pages today, but only as a side effect of Jekyll's default build silently excluding dot-prefixed paths -- no `.nojekyll` file is present. This is not a deliberate access control and it will stop working if hosting ever moves to Cloudflare Pages, or if `.nojekyll` is added here for true zero-build passthrough. Revisit how these paths stay unpublished before either of those changes.
