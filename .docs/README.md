# .docs

Repo-internal documentation for `schema-aggregator` -- architecture notes,
design decisions, contributor guides -- as opposed to the merged schema
content served publicly from the repo root.

This folder is dot-prefixed deliberately: GitHub Pages' current build
(legacy/Jekyll, no `.nojekyll`) silently excludes dot-prefixed paths, which
is also the only reason `.sync/` and `.github/` aren't publicly served
today. That's an accident of the current build mode, not a deliberate
access control -- it breaks the moment we move to Cloudflare Pages (still
an open decision in the schema-serving proposal) or add `.nojekyll` for
true zero-build passthrough. If either happens, revisit how `.docs/`,
`.sync/`, and `.github/` stay unpublished before making the switch.
