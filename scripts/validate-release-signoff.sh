#!/usr/bin/env bash
# Preserve the promotion workflow's entry point; the standard-library validator
# below keeps git ancestry, evidence parsing and negative cases testable.
set -eu
exec python3 "$(dirname "$0")/validate_release_signoff.py" "$@"
