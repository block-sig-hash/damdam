#!/usr/bin/env bash

set -u

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mobile_dir=$(cd "$script_dir/.." && pwd)
cd "$mobile_dir"

status=0
maestro test maestro/screens \
  --exclude-tags ios-only \
  --format junit \
  --output maestro-report.xml \
  --test-output-dir="$mobile_dir/maestro-output" || status=$?

# Keep artifact discovery visible in the job log even when a flow fails.
find maestro-output -maxdepth 4 -type f -print 2>/dev/null || true

exit "$status"
