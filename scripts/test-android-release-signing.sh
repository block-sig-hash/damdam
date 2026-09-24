#!/usr/bin/env bash
set -euo pipefail

# Local release-signing guard regression only. This does not prove EAS cloud
# signing, provider credentials or the signature of an actual AAB artifact.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -r -- "$test_dir"' EXIT
test_key="$test_dir/test-upload.jks"
test_password='ci-test-only-android-key'
test_alias='ci-test-upload'

keytool -genkeypair -noprompt -storetype JKS -keyalg RSA -keysize 2048 \
  -validity 1 -dname 'CN=CI test only' -keystore "$test_key" \
  -storepass "$test_password" -keypass "$test_password" -alias "$test_alias" \
  > /dev/null 2>&1
test_fingerprint=$(keytool -exportcert -keystore "$test_key" \
  -storepass "$test_password" -alias "$test_alias" 2>/dev/null | sha256sum | cut -d' ' -f1)

export DAMDAM_RELEASE_KEYSTORE_PATH="$test_key"
export DAMDAM_RELEASE_STORE_PASSWORD="$test_password"
export DAMDAM_RELEASE_KEY_ALIAS="$test_alias"
export DAMDAM_RELEASE_KEY_PASSWORD="$test_password"
cd "$repo_root/apps/mobile/android"

DAMDAM_RELEASE_CERT_SHA256="$test_fingerprint" ./gradlew bundleRelease --dry-run \
  --no-daemon > "$test_dir/approved.log" 2>&1 || {
    sed -n '1,100p' "$test_dir/approved.log" >&2
    exit 1
  }
if DAMDAM_RELEASE_CERT_SHA256=0000000000000000000000000000000000000000000000000000000000000000 \
  ./gradlew bundleRelease --dry-run --no-daemon \
  > "$test_dir/wrong-fingerprint.log" 2>&1; then
  echo 'Release signing accepted an unapproved fingerprint' >&2
  exit 1
fi
if ! rg -q 'does not match the approved DAMDAM_RELEASE_CERT_SHA256' \
  "$test_dir/wrong-fingerprint.log"; then
  sed -n '1,100p' "$test_dir/wrong-fingerprint.log" >&2
  exit 1
fi
if DAMDAM_RELEASE_CERT_SHA256="$test_fingerprint" ./gradlew bundleRelease --dry-run \
  --no-daemon --init-script "$repo_root/scripts/rebind-release-signing-test.init.gradle" \
  > "$test_dir/rebound-debug.log" 2>&1; then
  echo 'Release rebound to debug signing was accepted' >&2
  exit 1
fi
if ! rg -q 'matches the checked-in debug certificate' "$test_dir/rebound-debug.log"; then
  sed -n '1,100p' "$test_dir/rebound-debug.log" >&2
  exit 1
fi
echo 'Local release signing: test key accepted; wrong fingerprint and debug rebind rejected'
