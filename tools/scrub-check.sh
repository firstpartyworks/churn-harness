#!/usr/bin/env bash
# Refuse to commit internal references into a repo that ships publicly.
#
# This exists because remembering to scrub failed: run metadata was regenerated
# on every run, so scrubbing the file by hand was silently undone by the next
# invocation and shipped anyway. A rule that depends on noticing is not a rule.
#
#   scrub-check.sh              # staged changes only (pre-commit hook mode)
#   scrub-check.sh --all        # every tracked file (audit mode)
#   scrub-check.sh --self-test  # prove the check can actually fail
#
# Bypass for a deliberate exception: git commit --no-verify
set -uo pipefail

PATTERN='/bulk/|/fast/|/home/|chambejp|[Cc]hamberlain|(^|[^[:alnum:]])John([^[:alnum:]]|$)'

scan() {  # scan <file-list-on-stdin>
    local hits=0 f
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        case "$f" in *scrub-check.sh) continue;; esac   # the pattern list itself
        if grep -HnE "$PATTERN" -- "$f" 2>/dev/null; then hits=1; fi
    done
    return $hits
}

case "${1:-}" in
  --self-test)
      t=$(mktemp); printf 'model at /bulk/models/x.gguf\n' > "$t"
      if grep -qE "$PATTERN" "$t"; then rm -f "$t"; echo "self-test PASS: the check detects a known-bad line"; exit 0
      else rm -f "$t"; echo "self-test FAIL: pattern matches nothing -- the check cannot fail"; exit 2; fi ;;
  --all)
      echo "scrub-check: auditing every tracked file"
      if git ls-files | scan; then echo "scrub-check: CLEAN"; exit 0
      else echo; echo "scrub-check: internal references found above"; exit 1; fi ;;
  *)
      if git diff --cached --name-only --diff-filter=ACM | scan; then exit 0
      else
        echo
        echo "scrub-check: COMMIT REFUSED -- internal references in the staged changes."
        echo "This repository ships publicly. Remove the paths/names above, or fix the"
        echo "generator that writes them (output-only fixes get overwritten on the next run)."
        echo "Deliberate exception: git commit --no-verify"
        exit 1
      fi ;;
esac
