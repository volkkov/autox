# autox — Architecture

autox drives an Android phone on Android 16 with no uiautomator. It splits along
one line (see [ADR 0001](docs/adr/0001-no-uiautomator-accessibility-rpc-tree-source.md)):

- **Controls** — tap, swipe, key, screenshot, app-launch, orientation — run from
  the client over adb (`input` / `cmd` / `settings` / `screencap`). Nothing on
  the device.
- **Observation** — the UI tree — comes from a **device-side AccessibilityService**
  (the RPC server) over a loopback socket bridged by `adb forward`.

Domain terms are defined in [CONTEXT.md](CONTEXT.md); this file maps the modules
and seams.

## Modules

### Client (Python, `autox/`)

| Module | Interface | Depth |
| --- | --- | --- |
| `device.py` | `Device` — the u2-compatible surface (`ax.connect`, controls, `dump_hierarchy`, `info`, selectors via `__call__`). | Deep: one class fronts every adb control and the tree source. |
| `treesource.py` | `TreeSource.dump() -> str | None` — **the seam**. `RpcTreeSource` (production) and `StaticTreeSource` (tests). | Deep: one method hides adb-forward + HTTP + bring-up. |
| `selector.py` | `Selector` / `match_nodes` — resolve `d(text=…)` against Hierarchy XML, tap centers. | Deep: full u2 selector semantics, client-side. |
| `elements.py` | `compact_elements` — slim Hierarchy XML to the token-cheap element list. | Deep: the whole slimming policy behind one call. |
| `dump.py` | Pure XML helpers (trim, bounds, center). | Shallow by design — pure, unit-testable leaf. |
| `exceptions.py` | u2-name-compatible error types. | Leaf. |
| `selfcheck.py` | Live-device capability check (controls always; tree when the server is up). | Operational. |

### Server (Java, `server/`)

A single-module Android app — an `AccessibilityService`, no third-party deps.

| File | Role |
| --- | --- |
| `AutoxAccessibilityService.java` | Binds on enable, starts the RPC server, exposes `dumpHierarchy()`. |
| `HierarchyDumper.java` | Walks `getWindows()`/`getRootInActiveWindow()` → uiautomator-schema XML (absolute `getBoundsInScreen`). |
| `RpcServer.java` | Dependency-free loopback HTTP: `GET /ping`, `GET /dump`. |

## The seam

`TreeSource` is the one place the tree is produced. Two adapters make it real,
not hypothetical:

- `RpcTreeSource` — talks to the device-side server. Brings it up lazily on first
  `dump()`: enable the accessibility service + `adb forward`, both idempotent.
- `StaticTreeSource` — serves fixed XML, so the entire client (selectors,
  elements) is testable with no device and no server.

Swapping the tree source touches nothing downstream: the server emits the exact
uiautomator XML schema, so `dump.py`, `selector.py`, and `elements.py` are
source-agnostic. **Invariant:** Hierarchy XML is `<hierarchy>` of `<node>` with
uiautomator attribute names and `bounds="[l,t][r,b]"` in absolute screen pixels.

## Build & install the RPC server

The APK needs an Android SDK/JDK (absent in the dev container), so CI is the
canonical build.

1. **Build** — push to GitHub; `.github/workflows/build-apk.yml` builds
   `autox-server.apk` and uploads it as the `autox-server-apk` artifact. (Locally,
   with an Android SDK: `cd server && gradle wrapper --gradle-version 8.7 && ./gradlew assembleDebug`.)
2. **Install** — `adb install -r app-debug.apk`.
3. **Enable** — autox does this automatically on first `dump()`. Manual:
   ```
   adb shell settings put secure enabled_accessibility_services com.gitshrl.autox/com.gitshrl.autox.AutoxAccessibilityService
   adb shell settings put secure accessibility_enabled 1
   ```
4. **Verify** — `python -m autox.selfcheck --serial <SERIAL>` → `tree_source: ready`.

## Consuming autox from macrox

macrox switches its import and drives autox unchanged (the surface matches the u2
slice it uses):

```python
import autox as ax
from autox.exceptions import BaseException as U2BaseError
from autox.exceptions import UiAutomationNotConnectedError
# ... dev = ax.connect(serial)
```

Add autox as a dependency (`uv add ../autox` or a git dep) and `uv sync`. Until
the RPC server is installed, macrox degrades to its existing coordinate/vision
mode; once it's up, selector clicks work again on Android 16.
