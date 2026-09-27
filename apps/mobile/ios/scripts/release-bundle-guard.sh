#!/bin/sh
# Executed by React Native's with-environment.sh only after it sources
# .xcode.env and .xcode.env.local. A guard in the outer Xcode phase would miss
# a fixture switch injected by those files.
set -eu

if [ "${CONFIGURATION:-}" = Release ] && [ "${SCREENSHOT_HARNESS_MODE:-}" = true ]; then
  echo 'error: SCREENSHOT_HARNESS_MODE is forbidden in an iOS Release build' >&2
  exit 1
fi

exec "$REACT_NATIVE_PATH/scripts/react-native-xcode.sh"
