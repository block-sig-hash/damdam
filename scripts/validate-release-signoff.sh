#!/usr/bin/env bash
# Validates a staging->main release-signoff artifact for the promotion
# PR whose head commit is $1. See docs/infrastructure.md's
# "Amendment -- Three-Branch Promotion and Release Signoff Gate" for
# the full convention, and docs/release-signoffs/TEMPLATE.md for the
# exact field format this script parses. That format is load-bearing:
# changing a heading/label here without updating the template (or vice
# versa) will make real signoffs fail this check.
#
# Usage: validate-release-signoff.sh <pr-head-sha>
# Must run inside a checkout with full history (fetch-depth: 0) and
# both the PR head and `origin/main` present, since it uses
# `git merge-base` to find newly-added signoff files and to check
# ancestry.
set -u

PR_HEAD_SHA="${1:?usage: validate-release-signoff.sh <pr-head-sha>}"
SIGNOFF_DIR="docs/release-signoffs"
REQUIRED_MAX_AGE_DAYS=7

fail() {
  echo "::error::$1"
  exit 1
}

info() {
  echo "$1"
}

git rev-parse --verify --quiet "${PR_HEAD_SHA}^{commit}" >/dev/null \
  || fail "PR head commit ${PR_HEAD_SHA} is not resolvable in this checkout -- was checkout run with fetch-depth: 0?"

git rev-parse --verify --quiet "origin/main^{commit}" >/dev/null \
  || fail "origin/main is not resolvable in this checkout -- was checkout run with fetch-depth: 0?"

MERGE_BASE=$(git merge-base origin/main "${PR_HEAD_SHA}") \
  || fail "Could not compute a merge base between origin/main and ${PR_HEAD_SHA}. Is this PR actually targeting main?"

# --- Check 1: a signoff artifact exists for this promotion ---------------

mapfile -t ADDED_SIGNOFFS < <(
  git diff --name-only --diff-filter=A "${MERGE_BASE}" "${PR_HEAD_SHA}" -- "${SIGNOFF_DIR}" \
    | grep -v "/TEMPLATE\.md$" \
    | grep -v "/README\.md$"
)

if [ "${#ADDED_SIGNOFFS[@]}" -eq 0 ]; then
  fail "No release-signoff artifact found. This promotion PR must add exactly one new file at ${SIGNOFF_DIR}/<commit-sha>.md (see ${SIGNOFF_DIR}/TEMPLATE.md)."
fi

if [ "${#ADDED_SIGNOFFS[@]}" -gt 1 ]; then
  fail "Found ${#ADDED_SIGNOFFS[@]} new files under ${SIGNOFF_DIR}, expected exactly one signoff artifact: ${ADDED_SIGNOFFS[*]}"
fi

SIGNOFF_FILE="${ADDED_SIGNOFFS[0]}"
FILENAME_SHA=$(basename "${SIGNOFF_FILE}" .md)
info "Found signoff artifact: ${SIGNOFF_FILE}"

# --- Check 2: anti-staleness -- the declared SHA is real, matches the ----
# --- filename, and is actually part of what's being promoted here --------

echo "${FILENAME_SHA}" | grep -qE '^[0-9a-f]{40}$' \
  || fail "Signoff filename '${FILENAME_SHA}.md' is not a full 40-character commit SHA."

git rev-parse --verify --quiet "${FILENAME_SHA}^{commit}" >/dev/null \
  || fail "Signoff filename declares commit ${FILENAME_SHA}, which does not resolve to a real commit in this repository."

if ! git merge-base --is-ancestor "${FILENAME_SHA}" "${PR_HEAD_SHA}"; then
  fail "Signoff declares commit ${FILENAME_SHA}, which is not an ancestor of this PR's head (${PR_HEAD_SHA}) -- this looks like a stale signoff copied from a different (likely already-promoted) release, not one covering what's actually in this promotion."
fi

DECLARED_SHA=$(grep -oP '(?<=\*\*Commit SHA:\*\*\s)[0-9a-fA-F]{40}' "${SIGNOFF_FILE}" | head -n1)
if [ -z "${DECLARED_SHA:-}" ]; then
  fail "${SIGNOFF_FILE} has no parseable '**Commit SHA:** <sha>' line (or the SHA isn't a full 40 hex characters)."
fi
DECLARED_SHA_LOWER=$(echo "${DECLARED_SHA}" | tr '[:upper:]' '[:lower:]')
if [ "${DECLARED_SHA_LOWER}" != "${FILENAME_SHA}" ]; then
  fail "${SIGNOFF_FILE}'s internal '**Commit SHA:**' field (${DECLARED_SHA}) does not match its own filename (${FILENAME_SHA}.md) -- these must be identical."
fi

# --- Check 3: structural completeness -------------------------------------

TESTER=$(grep -oP '(?<=\*\*Tester name:\*\*\s).+' "${SIGNOFF_FILE}" | head -n1 | sed -E 's/^[[:space:]]*<.*>[[:space:]]*$//; s/[[:space:]]+$//')
[ -n "${TESTER:-}" ] || fail "${SIGNOFF_FILE} is missing a **Tester name:** value (or it's still the <placeholder>)."

DATE_RAW=$(grep -oP '(?<=\*\*Date:\*\*\s)[0-9]{4}-[0-9]{2}-[0-9]{2}' "${SIGNOFF_FILE}" | head -n1)
[ -n "${DATE_RAW:-}" ] || fail "${SIGNOFF_FILE} is missing a **Date:** value in YYYY-MM-DD format."

# US-30 (chunk 04E) emptied this list. Every scenario it required --
# incoming-call wake, CallKit lock-screen UI, PushKit delivery, offline
# check-in and offline SOS survival -- tested a feature chunk 04 retired.
# They could not be left in place: SCOPE-DISPOSITION.md forbids fabricating
# retired-feature evidence to pass this gate, so a truthful signoff could
# never satisfy them again.
#
# The list is deliberately NOT replaced with an empty loop that silently
# passes. Chunk 27 re-cuts the real release gates against the reset product
# and chunk 29 runs the physical-device pilot that produces the evidence; a
# gate that quietly approves everything in between is worse than no gate.
# Until chunk 27 defines them, this check fails loudly and says why.
#
# To define the new set, replace this block with a REQUIRED_SCENARIOS array
# and keep docs/release-signoffs/TEMPLATE.md's scenario table in step -- the
# two are parsed against each other.
fail "Release scenario requirements have not been re-cut since US-30 retired \
the incoming-call, CallKit/PushKit, offline check-in and offline SOS \
scenarios this gate used to require. Chunk 27 owns the replacement set. Do \
not bypass this by re-adding retired scenarios to the signoff."

for platform in "Android" "iOS"; do
  row=$(grep -E "^\| ${platform} \|" "${SIGNOFF_FILE}" | head -n1)
  [ -n "${row}" ] || fail "${SIGNOFF_FILE}'s device matrix table is missing an ${platform} row."
  echo "${row}" | grep -qE '<device model>|<OS version>' \
    && fail "${SIGNOFF_FILE}'s ${platform} device matrix row still has unfilled <placeholder> values."
done

HTO_SECTION=$(awk '/^## HTO usability test signoff/{flag=1; next} /^## /{flag=0} flag' "${SIGNOFF_FILE}" \
  | grep -v '^<!--' | grep -v '^-->' | tr -d '[:space:]')
[ -n "${HTO_SECTION:-}" ] || fail "${SIGNOFF_FILE}'s '## HTO usability test signoff' section is empty."

# --- Check 4: freshness ----------------------------------------------------

DATE_EPOCH=$(date -u -d "${DATE_RAW}" +%s 2>/dev/null) \
  || fail "${SIGNOFF_FILE}'s Date value '${DATE_RAW}' could not be parsed."
NOW_EPOCH=$(date -u +%s)
AGE_DAYS=$(( (NOW_EPOCH - DATE_EPOCH) / 86400 ))

if [ "${AGE_DAYS}" -gt "${REQUIRED_MAX_AGE_DAYS}" ]; then
  fail "${SIGNOFF_FILE} is dated ${DATE_RAW}, which is ${AGE_DAYS} days old -- signoffs older than ${REQUIRED_MAX_AGE_DAYS} days are not valid for promotion. Re-test and re-sign against the current commit."
fi

info "Release signoff for ${FILENAME_SHA} valid: tester=${TESTER}, date=${DATE_RAW} (${AGE_DAYS}d old)."
