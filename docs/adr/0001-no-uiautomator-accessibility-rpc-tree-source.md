# 0001 — No uiautomator: an AccessibilityService RPC server is the tree source

## Status

Accepted.

## Context

autox exists because `uiautomator2` (u2) is dead on Android 16. Reproduced on a
Samsung SM-A075F (Android 16, SDK 36): u2's device-side APK throws
`NullPointerException` in `androidx.test.uiautomator.UiDevice.setCompressedLayoutHeirarchy`
because `UiAutomation.getServiceInfo()` returns null (openatx/uiautomator2#1138).
`dump_hierarchy` and every selector that internally dumps go down with it.

Two families of alternative were considered for reading the UI tree:

1. **The AOSP `uiautomator dump` shell binary.** Works today (verified, ~2.5 s),
   but it *is* uiautomator — the same framework whose behaviour on this OS is the
   problem — and the constraint is no uiautomator dependency of any kind. It also
   spins up its own `UiAutomation` per call, which conflicts with other
   automation and is slow.
2. **Pure adb `dumpsys`.** Measured `dumpsys activity top` on the device: the
   View dump carries resource-ids and bounds but **no text** (0 `text=` across
   the whole dump) and spans multiple activities ambiguously. Unusable as the
   grounding tree for a text-driven agent.

Controls (tap/swipe/key/screenshot/app-launch/orientation) are not affected —
they already run over adb `input`/`cmd`/`settings` with no uiautomator.

## Decision

Get the UI tree from a **device-side AccessibilityService** (`server/`) that
walks the live accessibility tree (`getWindows()` / `getRootInActiveWindow()`)
and serves it as **uiautomator-schema XML** over a loopback HTTP socket bridged
by `adb forward`. autox reaches it through the `TreeSource` seam
(`RpcTreeSource`); the client-side selector, compact-element, and control layers
are unchanged.

The server emits the exact uiautomator XML schema so the existing parser and
selectors need no change. It is enabled over adb (no root):
`settings put secure enabled_accessibility_services …`. Controls stay independent
of it — a device without the server installed still drives fully; only the tree
is unavailable.

## Consequences

- **No uiautomator anywhere.** Not the `uiautomator2` pip package, not the AOSP
  `uiautomator` binary, not `am instrument`. Nothing tied to the broken stack.
- **A build step.** The APK needs an Android SDK/JDK, absent in the dev
  container. CI (`.github/workflows/build-apk.yml`) is the canonical build; the
  artifact is installed with `adb install -r`. The Python client and its logic
  are fully testable and verified without it; the APK itself is verified by the
  CI build and on-device once installed — not in the dev container.
- **Better than the shell dump once up.** A persistent service holds the a11y
  connection, so dumps avoid the per-call `UiAutomation` spin-up and don't
  conflict with other automation.
- **Graceful when absent.** With the server not installed, `TreeSource.dump()`
  returns None (a quiet miss), selectors report not-found, and the compact list
  is empty — while every control keeps working. `selfcheck` reports the exact
  bring-up state.
- **Events not exposed.** The server serves `/dump` only, so toast capture (an
  a11y-event feature) stays a stub, as it was under u2's fallback.
