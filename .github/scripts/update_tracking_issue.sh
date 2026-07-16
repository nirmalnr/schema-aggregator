#!/usr/bin/env bash
# Shared by sync.yml and sources-changed.yml -- both call sync_sources.py
# (directly or via sources_changed.py) and need the same tracking-issue
# create/update/close logic afterward. Kept in one place so it can't drift
# between the two callers.
#
# Requires: GH_TOKEN, HAS_FAILURES, VALIDATION_REPORT_PATH (env vars),
# and `gh repo set-default` or being run inside the repo's own checkout.
set -e

LABEL="sync-validation"
TITLE="Schema validation failures"
REPORT_PATH="${VALIDATION_REPORT_PATH:-/tmp/validation-report.md}"

gh label create "$LABEL" --color FBCA04 \
  --description "Schema sync validation failures" 2>/dev/null || true

EXISTING=$(gh issue list --label "$LABEL" --state open --json number --jq '.[0].number // empty')

if [ "$HAS_FAILURES" = "true" ]; then
  if [ -n "$EXISTING" ]; then
    gh issue edit "$EXISTING" --body-file "$REPORT_PATH"
    echo "Updated existing tracking issue #$EXISTING"
  else
    gh issue create --title "$TITLE" --label "$LABEL" --body-file "$REPORT_PATH"
    echo "Created new tracking issue"
  fi
else
  if [ -n "$EXISTING" ]; then
    gh issue comment "$EXISTING" --body "All sources passed validation as of this run — closing."
    gh issue close "$EXISTING"
    echo "Closed tracking issue #$EXISTING"
  else
    echo "No failures, no existing tracking issue — nothing to do."
  fi
fi
