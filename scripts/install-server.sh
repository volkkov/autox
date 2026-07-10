#!/usr/bin/env bash
# Install the autox RPC server APK, uninstalling any prior copy first.
#
# CI builds sign the debug APK with an ephemeral keystore, so `adb install -r`
# across rebuilds fails with INSTALL_FAILED_UPDATE_INCOMPATIBLE. The server is
# stateless, so a clean uninstall-then-install is the reliable path. autox
# enables the accessibility service and forwards the port on its first dump.
#
# Usage: scripts/install-server.sh <app-debug.apk> [serial]
set -euo pipefail

APK="${1:?usage: install-server.sh <app-debug.apk> [serial]}"
SERIAL="${2:-}"
ADB=(adb)
[ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")

"${ADB[@]}" uninstall com.gitshrl.autox >/dev/null 2>&1 || true
"${ADB[@]}" install "$APK"
echo "installed. run: python -m autox.selfcheck ${SERIAL:+--serial $SERIAL}"
