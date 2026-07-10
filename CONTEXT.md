# autox — Context

Client-side Android UI automation that works on Android 16, with no uiautomator
anywhere. A drop-in for the slice of `uiautomator2` that macrox drives. The split
that defines the system: **controls** run entirely from the client over adb;
**observation** (the UI tree) comes from a device-side AccessibilityService over
RPC. See [[adr-0001-no-uiautomator-accessibility-rpc-tree-source]].

## Language

**Device**:
The autox handle to one attached phone (`ax.connect(serial)`), exposing the
uiautomator2-compatible surface macrox calls.
_Avoid_: client, session, driver (as a noun for this object).

**Control**:
A device action autox performs over adb — `input` tap/swipe/key, `screencap`,
`cmd statusbar`, `settings` orientation, monkey app-launch. Needs nothing on the
device; verified working on Android 16.
_Avoid_: command, gesture (for the whole category).

**Tree source**:
The seam that yields the current UI hierarchy as XML — one method,
`TreeSource.dump() -> str | None`. Everything that reads the screen sits on it.
_Avoid_: provider, backend, dumper.

**RPC server**:
The device-side AccessibilityService (`server/`) that walks the live a11y tree
and serves it over a loopback HTTP port bridged by `adb forward`. The production
**Tree source**. No uiautomator, no `am instrument`.
_Avoid_: agent, atx-agent, instrumentation server.

**Hierarchy XML**:
The uiautomator-schema document the **Tree source** returns — `<hierarchy>` of
`<node>` with bounds/text/resource-id/class/clickable/…. The schema is fixed so
the parser and selectors are source-agnostic.
_Avoid_: dump (as a noun for the string), a11y dump.

**Selector**:
A client-side query — `d(text=…, instance=…)` — resolved against **Hierarchy
XML** in Python, then tapped by center. Restores `click_by_text/id/description`
that die on Android 16.
_Avoid_: locator, matcher, finder.

**Compact element list**:
The token-cheap observation (`dump_elements`) — **Hierarchy XML** slimmed to just
the actionable/labelled nodes as small dicts, for an LLM agent.
_Avoid_: ui elements (unqualified), a11y tree (for the slimmed form).

**Drop-in (`ax`)**:
autox imported as `import autox as ax`, standing in for `import uiautomator2 as u2`
with the same method surface, so macrox switches with an import change.
_Avoid_: shim, wrapper, adapter (for the whole library).

## Relationships

- A **Device** performs **Controls** directly over adb and reads the screen only
  through its **Tree source**.
- The **RPC server** is the production **Tree source**; a `StaticTreeSource`
  (fixed XML) is the test adapter — two adapters, so the seam is real.
- The **RPC server** emits **Hierarchy XML**; **Selectors** and the **Compact
  element list** resolve against it client-side.
- **Controls** never depend on the **Tree source** — a phone with no **RPC
  server** installed still taps, swipes, types, and screenshots.

## Flagged ambiguities

- "dump" meant both the act and the string. Resolved: the act is **Tree
  source**`.dump()`; the string is **Hierarchy XML**.
- "server" is always the device-side **RPC server**; there is no host-side
  server. The host is only the autox client library.
- uiautomator vs uiautomator2: neither is used. The pip package `uiautomator2`
  is gone, and the AOSP `uiautomator` shell binary is deliberately not used
  ([[adr-0001-no-uiautomator-accessibility-rpc-tree-source]]).
