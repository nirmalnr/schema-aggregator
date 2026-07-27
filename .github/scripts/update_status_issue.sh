#!/usr/bin/env bash
# Shared by sync.yml and sources-changed.yml -- both call sync_sources.py
# (directly or via sources_changed.py) and need the same "Repo Status"
# create/update logic afterward. Kept in one place so it can't drift
# between the two callers.
#
# Unlike update_tracking_issue.sh, this issue is NEVER closed -- it's a
# permanent, pinned summary of current repo state, meant to be visible
# even when everything is clean. If a human closes it by accident, the
# next run reopens it.
#
# Requires: GH_TOKEN, STATUS_REPORT_PATH (env var), and being run inside
# the repo's own checkout.
set -e

LABEL="repo-status"
TITLE="Repo Status"
REPORT_PATH="${STATUS_REPORT_PATH:-/tmp/status-report.md}"

gh label create "$LABEL" --color 0E8A16 \
  --description "Permanent summary of current repo state" 2>/dev/null || true

BODY=$(cat "$REPORT_PATH")

# Cross-link to the validation tracking issue, if one is currently open --
# keeps the two issues pointing at each other without duplicating the
# full error table here.
VALIDATION_ISSUE=$(gh issue list --label "sync-validation" --state open --json number --jq '.[0].number // empty')
if [ -n "$VALIDATION_ISSUE" ]; then
  BODY="$BODY

See #$VALIDATION_ISSUE for current validation issue details."
fi

# --state all: `gh issue list` defaults to open-only, but this issue is
# never closed by us, so "does it exist" must not depend on state -- a
# human closing it by accident must not cause a duplicate to get created.
EXISTING=$(gh issue list --label "$LABEL" --state all --json number --jq '.[0].number // empty')

if [ -n "$EXISTING" ]; then
  gh issue edit "$EXISTING" --title "$TITLE" --body "$BODY"
  STATE=$(gh issue view "$EXISTING" --json state --jq '.state')
  if [ "$STATE" = "CLOSED" ]; then
    gh issue reopen "$EXISTING"
    echo "Reopened status issue #$EXISTING (was closed)"
  fi
  echo "Updated status issue #$EXISTING"
else
  URL=$(gh issue create --title "$TITLE" --label "$LABEL" --body "$BODY")
  NUMBER=$(echo "$URL" | grep -oE '[0-9]+$')
  gh issue pin "$NUMBER"
  echo "Created and pinned status issue #$NUMBER"
fi
