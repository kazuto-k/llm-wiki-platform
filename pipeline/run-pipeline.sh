#!/bin/bash
# run-pipeline.sh: llm-wiki パイプラインの全ステップを実行する
#
# Usage:
#   ./run-pipeline.sh --type entity --entity-type team --title "Platform Team" --author "bob@company.com"
#
# Flow:
#   connector (branch + raw commit)
#     → curator (raw → curated)
#       → lint-checker (validation)
#         → merge (→ master)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="$HOME/workspace/llm-wiki-platform/test/wiki-remote.git"
WORK_DIR="/tmp/llm-wiki-pipeline-$$"

cleanup() {
    rm -rf "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== llm-wiki Pipeline ==="
echo ""

# ---- Step 1: Connector ----
echo "--- Step 1: Connector ---"
CONNECTOR_OUTPUT=$(python3 "$SCRIPT_DIR/connector.py" "$@")
echo "$CONNECTOR_OUTPUT"

# Extract branch name from connector output
BRANCH=$(echo "$CONNECTOR_OUTPUT" | grep "^branch=" | cut -d= -f2)
if [ -z "$BRANCH" ]; then
    echo "[FATAL] Could not determine branch name from connector output"
    exit 1
fi
echo ""
echo "Branch: $BRANCH"

# ---- Step 2: Clone repo on the branch ----
echo ""
echo "--- Step 2: Clone ---"
git clone "$REPO_URL" "$WORK_DIR"
cd "$WORK_DIR"
git checkout "$BRANCH"
echo "Working on branch: $BRANCH"
echo "Files:"
find . -name "*.md" -not -path "./.git/*" | sort

# ---- Step 3: Curator ----
echo ""
echo "--- Step 3: Curator ---"
python3 "$SCRIPT_DIR/curator.py" "$WORK_DIR" --branch "$BRANCH"

# ---- Step 4: Lint-checker ----
echo ""
echo "--- Step 4: Lint-checker ---"
python3 "$SCRIPT_DIR/lint-checker.py" "$WORK_DIR"
LINT_EXIT=$?

if [ $LINT_EXIT -ne 0 ]; then
    echo ""
    echo "[PIPELINE] Lint check FAILED. Merge BLOCKED."
    echo "[PIPELINE] Fix errors and re-run curator."
    # Cleanup temp branch
    git push origin --delete "$BRANCH" 2>/dev/null || true
    exit 1
fi

# ---- Step 5: Merge ----
echo ""
echo "--- Step 5: Merge ---"
python3 "$SCRIPT_DIR/merge.py" "$WORK_DIR" --branch "$BRANCH"

echo ""
echo "=== Pipeline SUCCESS ==="
echo "Branch: $BRANCH → merged to master"
echo "Wiki.js will sync within 5 minutes (or trigger manually)."
