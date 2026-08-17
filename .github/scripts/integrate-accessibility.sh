#!/usr/bin/env bash
set -euo pipefail

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git fetch origin feat/accessibility-foundation

git checkout FETCH_HEAD -- \
  docs/accessibility.md \
  packages/rakit-web/src/rakit_web/accessibility.py \
  packages/rakit-web/src/rakit_web/assets.py \
  packages/rakit-web/src/rakit_web/assets/rakit.css \
  packages/rakit-web/src/rakit_web/resource_routes.py \
  packages/rakit-web/src/rakit_web/static/rakit-ui.js \
  packages/rakit-web/src/rakit_web/static/rakit.css \
  packages/rakit-web/src/rakit_web/static/theme.js \
  packages/rakit-web/src/rakit_web/templates/base.html \
  packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html \
  packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html \
  packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html \
  packages/rakit-web/src/rakit_web/templates/dashboard/index.html \
  packages/rakit-web/src/rakit_web/templates/resources/_table.html \
  packages/rakit-web/src/rakit_web/templates/resources/detail.html \
  packages/rakit-web/src/rakit_web/templates/resources/list.html \
  packages/rakit-web/tests/test_accessibility_contracts.py \
  packages/rakit-web/tests/test_accessibility_helpers.py \
  packages/rakit-web/tests/test_dashboard_runtime.py \
  packages/rakit-web/tests/test_query_ui.py \
  packages/rakit-web/tests/test_theme.py \
  packages/rakit-web/tests/test_write_forms.py \
  packages/rakit/src/rakit/cli.py \
  packages/rakit/tests/test_run_cli.py \
  tests/examples/test_read_examples.py

git rm .github/workflows/integrate-accessibility.yml .github/scripts/integrate-accessibility.sh
git add -A
git commit -m "chore: integrate accessibility after storage"
git push origin HEAD:integrate/accessibility-after-storage
