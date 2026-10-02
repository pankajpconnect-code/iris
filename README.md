# Iris

**Internal use only — OakNorth.** Not for external distribution.

A native macOS app: an API console (collections, environments, tests, and a
CSV batch runner) for the lending APIs.

## Running it

Double-click `Iris.app`. On first launch it bootstraps its own virtual
environment (`.venv`) using whichever of these it finds first with
Python ≥ 3.11:

1. `/opt/homebrew/bin/python3`
2. `/usr/local/bin/python3`
3. `/Library/Frameworks/Python.framework/Versions/*/bin/python3`

It never falls back to `/usr/bin/python3` (the macOS system Python, often an
old 3.9) — if nothing qualifies, it shows a native alert naming the problem
instead of silently running on the wrong interpreter.

No Terminal window opens. No browser tab opens. It's a normal Dock app with
its own window and menu bar.

**Single-instance probe:** before starting anything, launch GETs `/api/runs`
on the target port with a 0.5s timeout; a JSON body containing a `"runs"`
key means an instance is already up. If so, a native alert tells the user
to switch to it instead, and the second launch exits without ever starting
its own server — this is what stops two instances writing to the same
flat-file stores concurrently.

**Quit guard:** on window-close, checks whether a Runner batch is currently
in flight. If none, it quits immediately. If one is running, a blocking
native dialog names the run and its current iteration and warns that
quitting now stops it — but since runs are checkpointed to disk
continuously, confirming "Quit Anyway" only abandons the one in-flight HTTP
call, not any already-checkpointed results. Cancel is the default button.
This has nothing to do with unsaved console edits — those are a separate,
undialogued discard (see Request tabs below).

### From the command line (for development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python desktop_app.py
```

Defaults to port 5090 (`IRIS_PORT` to override, `IRIS_STRICT_PORT=1` to
fail instead of scanning for a free port, `IRIS_NO_BROWSER` is irrelevant
here — the desktop app never opens a browser).

## Where things are stored

- Collections: `collections/`
- Environments: `environments/` (secret-named variables — matching
  `token`/`secret`/`password`/`cookie` — are **never** written to these JSON
  files; only their *names* are, so a relaunch knows which Keychain item to
  look up. Values live in the macOS Keychain, under a service named
  `iris:<environment-slug>`)
- Run history: `runs/`
- Logs: `iris.log` (app) and `iris-bootstrap.log` (venv bootstrap, from the
  launcher script)

All of the above are gitignored.

## Console basics

- **Body modes:** `raw` (JSON, with syntax highlighting and `{{var}}` token
  coloring via a hand-rolled textarea overlay — no editor dependency, since
  there's no build step) and `x-www-form-urlencoded` (key/value rows or a
  bulk-text editor, same interaction pattern as the Headers tab).
- **Params tab is a pure view over the URL's query string** — there is no
  separate params field on a saved/sent request. Editing a param row updates
  the URL field immediately (on every keystroke); editing the URL field only
  re-parses back into Params rows on blur/Enter (not every keystroke), so an
  in-progress edit in either place doesn't fight the other. A disabled param
  round-trips through the URL via a `~`-prefixed key rather than being
  dropped.
- **Theme:** light/dark toggle in the top bar, persisted to
  `localStorage["iris-theme"]`. With nothing stored yet, it follows the OS's
  `prefers-color-scheme` and keeps following live OS changes until the user
  picks a theme explicitly.

## Request tabs

Each request clicked in the sidebar opens as its own tab; switching between
tabs preserves in-progress edits and that tab's last response. A brand-new
unsaved request also gets its own tab ("Untitled") — several can be open at
once, named only once saved.

A "●" dot on a tab marks unsaved edits. Closing a tab (✕, or via Close
Other/All Tabs in its right-click menu) is a **silent discard** — there is
no confirm-on-close prompt, so unsaved edits in a closed tab are gone.
Tabs are in-memory only — they don't persist across a reload or app
relaunch; every session starts with no tabs open.

## Searching requests

The sidebar's search box is a substring filter over request names only
(`static/sidebar.js`) — case-insensitive, not method or URL. A collapsed
collection or folder containing a match auto-expands while the filter is
active; clearing the search box restores each one's own manually-set
collapsed/expanded state rather than leaving it forced open.

## Environments

Two variable scopes: collection-level (`collection_store.py`) and
environment-level (`environment_store.py`) — no global scope. When a
request is sent, environment variables are merged on top of collection
variables, taking precedence on key collisions
(`environment_store.merge_variables`); any per-run capture/override
values win over both.

The active environment is a per-browser-session choice — a dropdown
picks it, persisted in `localStorage` under
`csvApiConsole.activeEnvironmentSlug` (`static/environments.js`), not
written to disk per collection. Switching never mutates the environment
itself, only which one requests resolve against.

Variable substitution uses `{{varName}}` in URLs, headers, bodies, and
assertion `expected` values — matched by a single pattern (`_VAR_PATTERN`
in `assertions.py`) reused everywhere substitution happens, so behavior
stays identical between the console, the assertion engine, and the CSV
batch runner.

A separate **Vars tab** on each request shows collection-scoped variables
the user explicitly defined — via **+ Variable**, or written by a Capture
test row when it runs — not every `{{var}}` the request happens to
reference, and not environment variables (those stay in the Environments
modal; showing them in both places would just duplicate them). A missing
variable still warns before Send, checking both sources together.
Secret-named variables here (matching `token`/`secret`/`password`/`cookie`)
are genuinely **session only**: kept in an in-memory dict, never written to
the on-disk per-collection vars file — unlike environment secrets, they
aren't even in the Keychain, so they are lost on app restart and must be
re-entered.

## Auth

Auth is configured **per collection**, not per request
(`templates/index.html`) — every request in a collection shares one auth
config. Supported modes (`static/request-tabs.js`, `AUTH_MODE_LABELS`):

- **Bearer** — a static token
- **Basic** — username/password, plus a tenant header
- **API Key** — name/value pair; defaults to a header location
- **Cookie→Bearer** (`refresh-cookie` mode) — mints a bearer token from a
  refresh-token cookie/env var against a configured token URL
- **OAuth2** (`oauth2-client-credentials` mode) — RFC 6749 §4.4
  client-credentials grant, `basic-header` or body-embedded client auth
  style (`oauth2_client_credentials.py`)

For the two token-minting modes, `run_auth.py`'s `TokenCache` mints at most
one token per Runner run (single-flight, safe under parallel workers) and
auto-refreshes on a configurable set of response statuses — default
`{401, 403}`, overridable via `authRetryStatuses` — up to a max-refresh
cap, with a circuit breaker after repeated consecutive mint failures. A
row whose own test assertions explicitly expect the observed status is
never retried.

Secrets (bearer tokens, basic passwords, API key values, OAuth2 client
secrets) are redacted to `***` on collection export whenever the value is
a literal — a `{{variable}}` reference is left intact since it's a
pointer, not a secret (`collection_io.py`).

## Folders

Requests can be grouped into one-level folders within a collection
(`folder_routes.py`, `static/folders.js`) — create, rename, delete, and
move a request into/out of a folder via the sidebar's right-click menu
("New Folder" on a collection, "Move to Folder" on a request). Deleting a
folder never deletes its requests — they fall back to "Uncategorized"
(`collection_store.py`'s `delete_folder`). Folders don't nest.

This is separate from collection import/export: a nested `item` structure
in an imported v2.1 collection is flattened into `"Parent / Child / Name"`
prefixed request names (`collection_io.py`'s `_walk`), not turned into
real folder objects, and native folders aren't written back out on export
— the two folder concepts don't currently round-trip through each other.

## Importing collections

On import (`collection_io.py`), recognised test-script assertions and
variable captures are auto-translated into declarative Tests-tab rows —
no JS engine involved. Anything that doesn't match a known pattern is kept
as `untranslated` text rather than silently dropped, so nothing imported is
ever lost, just left for manual conversion.

Recognised patterns include: variable capture from a response field,
existence/not-null/not-empty checks, an equality check, and a response
status-code check (`{"source": "status", "operator": "equals", ...}`).
The declarative row shape and its full operator set (`equals`, `notEquals`,
`exists`, `notNull`, `notEmpty`, `contains`, `matches`, `gt`, `gte`, `lt`,
`lte`) are implemented in `assertions.py` and run identically whether a
request came from import or was authored directly in the Tests tab —
including in the CSV batch runner (`run_api_from_csv.py`), where they
double as a per-row pass/fail column.

### Importing from curl

Right-click a collection → **Import from curl** → paste a curl command.
Parses `-X`/`--request`, `-H`/`--header`, body flags
(`-d`/`--data`/`--data-raw`/`--data-binary`/`--data-ascii`, concatenated
with `&` on repeats; `--data-urlencode`, URL-encoded), and `-u`/`--user`
(converted to a `Basic` `Authorization` header). Method defaults to `GET`,
or `POST` if a data flag is present. Body mode is inferred `urlencoded` vs
`raw` from a `Content-Type` header containing `x-www-form-urlencoded`.

Flags with no request-field equivalent are grouped two ways: silent
no-ops that take no argument (`-k`, `-L`, `--compressed`, `-s`, `-v`,
`-i`, `--http1.1`, `--http2`, etc.) are dropped without comment, while
flags that take a value but aren't supported (`-F`/`--form`,
`-b`/`--cookie`, `-A`/`--user-agent`, `-x`/`--proxy`,
`-T`/`--upload-file`, `-o`/`--output`, `-w`/`--write-out`,
`-m`/`--max-time`, `--connect-timeout`, `--cert`, `--key`,
`-e`/`--referer`) are explicitly listed, consumed, and surfaced in a
post-import alert naming exactly which flags were skipped — never
silently (`static/curl-import.js`).

## Exporting collections

Exports exactly one collection at a time — whichever is selected in the
sidebar — via **↓ Export**, which writes `<slug>.collection.json` through
the same native-save-dialog bridge used elsewhere in the app. There's no
export-all or multi-select.

Output is the same v2.1-schema shape import reads (`collection_io.py`'s
`to_collection`), so it round-trips cleanly through Iris itself. Declarative
Tests rows and per-request auth are included as extra, non-standard fields
so a re-import gets them back — a real external v2.1-consuming tool should
just ignore fields it doesn't recognize. Secrets are redacted the same way
noted under Auth above, applied uniformly to headers, urlencoded body
params, and auth fields, not just auth. Folders do **not** survive export
— consistent with the Folders section above: export builds a flat `item`
list with no folder field anywhere, so re-importing an exported collection
loses folder grouping.

## Saving a response

"Save Response" is enabled only once a real, non-error response with a
body exists — disabled again on Send and on tab switch/close until the
next successful response lands. It saves the response **body only**
(headers/status aren't included) to a file, named
`<request-name>-response.json` or `.txt` depending on whether the body
parsed as JSON, via a native macOS Save As dialog (`save_bridge.py`) — not
a fixed location. The same native-save bridge also backs "Export request,"
"Export collection," and the Runner's "Export as CSV."

## Runner (CSV batch execution)

Runs one or more saved requests repeatedly — once per row of an uploaded
CSV — and grades each row against the same declarative assert/capture
rows described above, producing a pass/fail column per row rather than a
single pass/fail per request.

- **Scope**: a single request, a folder (including nested children), or
  an entire collection, with an inline checklist to exclude individual
  requests from a folder/collection scope without changing the scope
  type.
- **Chaining**: a captured variable from one row/step is available to the
  next — CSV columns take precedence over captures, which take precedence
  over environment/collection variables.
- **Retry**: unconditional single retry on a 403 (token-expiry
  heuristic), plus opt-in exponential-backoff retry (with jitter) for
  idempotent methods on a transient failure (5xx or timeout) — an
  assertion mismatch is never retried, only transport/server failures
  are.
- **Per-attempt visibility**: every real HTTP attempt is streamed live
  (attempt number, status, whether a retry will follow), not just a
  final count.
- **Parallel execution**: opt-in via a worker count > 1 — iterations run
  concurrently; requests *within* one iteration always run in order,
  since a later request in the same row can depend on an earlier one's
  captured value.
- **History**: every run is checkpointed incrementally to `runs/` (also
  exportable as CSV) so a crashed or long-running batch survives a
  restart and stays inspectable afterwards.

A companion standalone CLI, `run_api_from_csv.py`, covers the same
CSV-driven-request-plus-assertions idea outside the app, for scripting or
CI use.

## Settings (proxy, timeout, TLS verification)

Reachable via **⚙ Settings** in the topbar. Settings are global (not
per-environment or per-request) and persisted in `localStorage`, applied
to both the Console's single Send and every row the CSV Runner sends.

- **Proxy** (`iris.proxySettings`) — three modes: `system` (default;
  passes `proxies=None` so the HTTP client discovers OS/env proxy config
  itself, including its own `NO_PROXY` handling), `env` (reads
  `HTTP_PROXY`/`HTTPS_PROXY` directly, independent of OS config, with its
  own `NO_PROXY` bypass check), and `custom` (a user-supplied proxy URL,
  with optional username/password credentials embedded in the URL). A
  per-host bypass list is also supported and is checked before any mode
  logic runs. Resolution lives in `proxy_resolver.py`.
- **Timeout** (`iris.requestTimeoutSeconds`) — defaults to 120s in the
  UI; if the field is omitted entirely, the backend itself falls back to
  30s.
- **TLS verification** (`iris.insecureMode`) — a global checkbox; when
  enabled, disables certificate verification (`verify=False`) for every
  outbound request. No confirmation dialog or logging currently warns
  when this is on — it's a silent global toggle, so leaving it enabled is
  easy to forget.

## Native macOS integration

- **Menu bar** (`menu.py`): Iris (About, Quit) · File (New Request, Import
  Collection…, Export Collection…, Manage Environments…) · Edit (Beautify
  Body, Bulk Edit Headers) · Collection (Duplicate/Save Request, Save Auth,
  Send Request) · Run (Console/Runner view switch, Preview, Run, Stop,
  History, Export Results…) · Window (Minimize, Toggle Full Screen) · Help
  (README pointer). Every action just synthesizes a click on the matching
  frontend button id, so behavior always matches clicking that button
  directly — there's no separate native code path to drift out of sync.
- **Native file/folder pickers** (`native_pickers.py`): used for the
  Runner's CSV input and failed-rows output folder, served from `server.py`
  at `/api/choose-csv` and `/api/choose-output-folder`. A user-cancelled
  picker is a distinct outcome, not an error — the frontend can tell "user
  backed out" apart from "picker actually failed."

## Known limitations

- **No keyboard accelerators on menu items.** pywebview 6.2.1's `MenuAction`
  has no accelerator/shortcut parameter at all (its own source has a
  `# TODO: support platform-agnostic shortcut` next to an unused,
  commented-out field) — this isn't a bug in this app, it's unsupported
  upstream. Every menu item works when clicked; none show a ⌘-shortcut in
  the menu bar. This is a **native menu item** limitation only — in-page
  keyboard shortcuts (⌘S save, ⌘Enter send, ⌘F find, ⌘C/⌘X copy/cut) are
  plain JS `keydown` handlers (`static/shared.js`, `static/body-editor.js`)
  and work normally; they don't go through `MenuAction` at all.
- **Clipboard copy goes through a Python bridge, not `navigator.clipboard`.**
  WKWebView denies `navigator.clipboard` calls made without a re-verified
  user-gesture context pywebview doesn't provide (`NotAllowedError`).
  "Copy as JSON" / "Copy as cURL" call
  `window.pywebview.api.clipboard_write`, which shells out to `pbcopy` —
  works identically from the user's point of view.
- **macOS only.** No Windows/Linux build — the app relies on `osascript`,
  the macOS `security` CLI, and pywebview's Cocoa backend throughout.
- **Unsigned.** No code-signing identity exists for this build, and
  signing/notarizing is out of reach here. Because it's delivered via `git
  pull` rather than downloaded (which is what stamps
  `com.apple.quarantine`), Gatekeeper does not block it. The app's launcher
  (`Iris.app/Contents/MacOS/iris`) is a shell script rather than a Mach-O
  binary for the same reason — a shell script needs no ad-hoc code
  signature on arm64, where an unsigned Mach-O binary would require one.

## Architecture note

The backend is its own stdlib `http.server` (`ThreadingHTTPServer` +
`BaseHTTPRequestHandler`) — no external web framework. `server.py`'s
request handler dispatches each request through a chain of `*_routes.py`
modules split by resource type (`collection_routes`, `environment_routes`,
`folder_routes`), falling through to the next module until one handles the
path. The frontend (`static/*.js`) talks to this over plain `fetch()`
calls to a local JSON API — the only non-HTTP bridges are the
pywebview-specific ones (native pickers, clipboard, save) covered above.

## Layout

```
server.py  collection_*.py  environment_*.py  ...  # backend modules
run_api_from_csv.py  assertions.py                 # CSV batch runner + assertion engine
templates/index.html  static/*                     # frontend
desktop_app.py                                     # entry point: server thread + window + quit guard
desktop_runtime.py                                 # Python resolution + single-instance probe
menu.py                                            # native macOS menu bar
save_bridge.py  static/save_bridge.js              # native save dialogs + clipboard bridge
keychain.py                                        # macOS Keychain wrapper (`security` CLI)
icon/make_icon.py  icon/Iris.icns
Iris.app/                                          # the launchable bundle
test_*.py                                          # test suite
```
