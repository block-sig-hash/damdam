#!/usr/bin/env bash
# Validate relative Markdown links across the repository's documentation.
#
# Added by chunk 01 to satisfy US-27 / AC-27.7. It is deliberately NOT wired
# into CI here -- CI configuration is chunk 02's scope. Run it by hand, or from
# a CI job that chunk 02 adds:
#
#     bash docs/implementation/tools/check-docs-links.sh
#
# Checks every [text](target) relative link in *.md under the repository root
# (excluding node_modules and .git). Skips http(s):, mailto: and in-page
# anchors. Resolves a "#fragment" suffix away before testing the path.
# Exits non-zero and lists every unresolved target.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root" || exit 2

broken=0
checked=0

while IFS= read -r -d '' file; do
  dir="$(dirname "$file")"
  # Extract link targets: [..](target)
  while IFS= read -r target; do
    [ -z "$target" ] && continue
    case "$target" in
      http://*|https://*|mailto:*|'#'*) continue ;;
    esac
    path="${target%%#*}"
    [ -z "$path" ] && continue
    checked=$((checked + 1))
    if [ ! -e "$dir/$path" ]; then
      echo "BROKEN  $file -> $target"
      broken=$((broken + 1))
    fi
  done < <(grep -oE '\]\([^)[:space:]]*\)' "$file" 2>/dev/null | sed -E 's/^\]\(//; s/\)$//')
done < <(find . -name '*.md' -not -path './node_modules/*' -not -path '*/node_modules/*' -not -path './.git/*' -print0)

echo "---"
echo "checked $checked relative links"
if [ "$broken" -gt 0 ]; then
  echo "FAILED: $broken broken link(s)"
  exit 1
fi
echo "OK: no broken relative links"
