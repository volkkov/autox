# uiautomator2 coverage

Every public uiautomator2 (u2) API mapped to autox. Legend: **✅ covered** ·
**⚠️ partial** (note) · **🚫 gap** (plan) · **➖ n/a** (u2-internal).

autox splits u2's monolith: **controls** run over adb (via
[openatx/adbutils](https://github.com/openatx/adbutils), the same layer u2 uses);
the **tree** and **text input** come from autox's own device-side APK — the
AccessibilityService RPC server plus a bundled IME — so there is no uiautomator
and no external ADBKeyboard/atx-agent dependency.

## Connection & device

| u2 | autox | |
| --- | --- | --- |
| `connect()` | `ax.connect()` | ✅ |
| `info` | `d.info` | ✅ displayRotation/size/sdk/package |
| `device_info` | `d.device_info` | ✅ serial/sdk/brand/model/arch/version |
| `window_size()` | `d.window_size()` | ✅ |
| `app_current()` | `d.app_current()` | ✅ fast path (`dumpsys window displays`, ~45ms on A16) |
| `serial` / `wlan_ip` | `d.serial` / `d.wlan_ip` | ✅ (adbutils) |
| `shell` / `adb_device` | `d.shell` / `d.adb_device` | ✅ |

## App management

| u2 | autox | |
| --- | --- | --- |
| `app_start` | `d.app_start` | ✅ monkey LAUNCHER (split-APK safe) |
| `app_stop` / `app_clear` | same | ✅ adbutils |
| `app_stop_all` | `d.app_stop_all` | ✅ third-party only |
| `app_install` | `d.app_install` | ✅ adbutils (path or URL) |
| `app_uninstall` | `d.app_uninstall` | ✅ |
| `app_list` / `app_list_running` | same | ✅ |
| `app_info` | `d.app_info` | ✅ adbutils `package_info` |
| `app_wait` / `wait_activity` | same | ✅ poll |
| `app_icon` | — | 🚫 icon extraction; low value |
| `session` | — | 🚫 lifecycle context; use app_start + app_wait |

## Controls: touch / key / screen

| u2 | autox | |
| --- | --- | --- |
| `click` `double_click` `long_click` | same | ✅ adbutils |
| `swipe` `swipe_ext` `swipe_points` `drag` | same | ✅ |
| `touch.down/move/up` | `d.touch.*` | ✅ `input motionevent` |
| `press` / `keyevent` | same | ✅ names + keycodes (adbutils) |
| `pos_rel2abs` | same | ✅ |
| `screen_on/off` `unlock` | same | ✅ |
| `orientation` `set_orientation` `freeze_rotation` | same | ✅ |
| `screenshot` | `d.screenshot()` | ✅ PIL |
| `screenrecord` | `d.start_recording/stop_recording/is_recording` | ✅ adbutils |
| `dump_hierarchy` | `d.dump_hierarchy()` | ✅ via RPC a11y server |

## Text input & IME

All typing routes through autox's **bundled IME** (`AutoxIME`, an ADBKeyboard
reimplementation in `server/`) for UTF-8/emoji; falls back to adbutils `send_keys`
(ASCII) if the IME can't be brought up.

| u2 | autox | |
| --- | --- | --- |
| `send_keys(text, clear)` | same | ✅ bundled IME |
| `clear_text` | `d.clear_text` | ✅ IME `ADB_CLEAR_TEXT` |
| `send_action` | `d.send_action` | ✅ IME editor action |
| `hide_keyboard` | same | ✅ |
| `current_ime` `set_input_ime` `is_input_ime_installed` | same | ✅ |

## Selectors — `d(**kwargs)` → `UiObject`

Resolved **client-side** against the RPC tree (this is what dies on Android 16 in
u2). Kwargs: `text/textContains/textMatches/textStartsWith`,
`description*`, `resourceId/resourceIdMatches`, `className/classNameMatches`,
`packageName`, the boolean states (`clickable`, `checked`, `scrollable`, …), and
`instance`.

| u2 UiObject | autox | |
| --- | --- | --- |
| `exists` `wait` `wait_gone` `must_wait` | same | ✅ |
| `info` `get_text` `bounds` `center` | same | ✅ |
| `set_text` `clear_text` `send_keys` | same | ✅ focus + IME |
| `click` `click_exists` `click_gone` `long_click` | same | ✅ |
| `drag_to` `swipe` `scroll` `fling` | same | ✅ within-element gesture |
| `screenshot` | same | ✅ cropped |
| `count` `len()` `[i]` `iter()` | same | ✅ |
| `child` `child_by_text` `child_by_description` `child_by_instance` | same | ✅ |
| `sibling` `parent` `left` `right` `up` `down` | same | ✅ |
| `pinch_in` `pinch_out` `gesture` | — | 🚫 multi-touch; plan: `/gesture` RPC → `dispatchGesture` |

## XPath — `d.xpath(...)`

| u2 | autox | |
| --- | --- | --- |
| `d.xpath('//…').click/get_text/set_text/wait/all/get` | `XPathSelector` | ✅ (inherits UiObject) |
| `@resource-id` / bare-text shorthands | `normalize_xpath` | ✅ |
| `contains()`, functions, `and`/`or` | | ⚠️ needs lxml — `pip install autox[xpath]`; else ElementTree attribute-predicate subset |

## Watchers, clipboard, files, settings

| u2 | autox | |
| --- | --- | --- |
| `watcher` `watch_context` `wait_stable` | `d.watcher` / `d.watch_context()` | ✅ client-side poller (`when().click/press/call`, `run/start/stop`) |
| `clipboard` / `set_clipboard` | same | ✅ via autox's own server (the IME app owns `ClipboardManager` access); clipper is dead on Android 16 (its APK targets SDK 0, install rejected) |
| `push` / `pull` | same | ✅ adbutils sync |
| `open_notification` `open_quick_settings` `open_url` | same | ✅ |
| `settings[...]` `implicitly_wait` `wait_timeout` | same | ✅ dict + wait timeouts |
| `sleep` | `d.sleep` | ✅ |
| `start_uiautomator` / `stop_uiautomator` / `reset_uiautomator` | same | ✅ maps to RPC-server bring-up |

## Genuine gaps (with the plan)

| u2 | why | plan |
| --- | --- | --- |
| `image` (template match) | needs OpenCV | optional `autox[image]` extra + `cv2.matchTemplate` over `screenshot()` |
| `toast` / `last_traversed_text` / `make_toast` | needs the a11y **event** stream | add an event buffer + `/toast` endpoint to the RPC server |
| `pinch_in/out`, `gesture` | multi-finger injection | add `/gesture` RPC → `AccessibilityService.dispatchGesture` |
| `jsonrpc` / `jsonrpc_call` | ➖ | n/a — autox has no jsonrpc server; the a11y RPC replaces it |
| `debug` / `show_touch_trace` / `show_float_window` | dev toggles | `settings put system show_touches 1` if needed; low value |
