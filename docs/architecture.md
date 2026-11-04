# Architecture

## Layers

1. Browser installation: one copy of each browser an identity uses, located per
   platform and launched natively on Apple Silicon
2. Profile: primary identity/data boundary. Firefox keeps
   `data/<name>/profile`; every other browser uses
   `data/<name>/profile-<browser>`, so switching browsers does not touch an
   existing Firefox profile
3. `identities/*.conf`: the single declarative source for one identity,
   including which `BROWSER` it launches, shared between machines
4. `mif/`: cross-platform core, shared by macOS and Windows
5. Engine-specific profile state: `user.js` for Firefox; a merged
   `Default/Preferences` plus command-line switches for Chromium-based
   browsers
6. `TZ` environment variable: web-visible timezone, read through ICU
7. Launcher: `.app` bundle on macOS, `.lnk` shortcut on Windows, named
   `<Browser> - <Identity>`

`user.js` is regenerated on every Firefox launch, so the conf file always wins
over anything changed in `about:config`. The Chromium keys this project owns
are merged back into `Preferences` on every cold start. A running Chromium
process is left alone: it rewrites `Preferences` from memory on exit and would
discard the update.

## Module layout

| Module | Responsibility |
| --- | --- |
| `mif/config.py` | Parse `identities/*.conf`, resolve per-identity paths |
| `mif/binpath.py` | Find a browser executable, detect the arm64 slice |
| `mif/tz.py` | Timezone resolution for both engines |
| `mif/browsers/gecko.py` | Firefox: render `user.js`, build its command line |
| `mif/browsers/chromium.py` | Chrome, Edge, Brave, Chromium: flags and Preferences |
| `mif/launchers.py` | Build and install per-identity launchers |
| `mif/cli.py` | `setup`, `launch`, `status`, `new-identity`, `wipe`, `install` |

`bin/*.sh` and `bin/*.cmd` are one-line wrappers around `python3 -m mif`.

## What is isolated

- Cookies
- LocalStorage
- IndexedDB
- Cache
- History
- Extensions
- Downloads
- Browser preferences
- Proxy configuration

## What is made regionally consistent

- Public IP, via a per-identity proxy rather than the system proxy
- Timezone (`TZ` on POSIX). Firefox additionally has a Windows whitelist.
  Chromium on Windows cannot express a timezone through `TZ`
- Language. Firefox uses `intl.*`. Chromium sets `navigator.languages` with
  `--accept-lang` and `intl.accept_languages`. On macOS the Chromium UI and
  the `Intl` default locale stay on the host language
- Geolocation coordinates, in Firefox only. A Chromium identity that sets
  coordinates denies the permission instead of pinning a position

## Leak paths that are closed

- Proxy failure falling back to a direct connection
- WebRTC ICE candidate enumeration outside the proxy
- DNS prefetch and the network predictor
- Chromium inheriting the system proxy when the identity asks for a direct
  connection (`--no-proxy-server`)

## Platform constraints

Firefox only honours a fixed set of `TZ` values on Windows, enforced by
`IsOlsonCompatibleWindowsTimeZoneId` in `js/src/vm/DateTime.cpp`. Zones outside
that set are silently ignored in favour of the host timezone. `mif/tz.py` maps
the zones whose DST rules match the POSIX aliases and refuses to generate a
launcher for the rest, unless the identity opts in with
`TIMEZONE_FALLBACK="host"`. The refusal happens at `setup` time because a GUI
launcher has no console to print a warning to.

Chromium on Windows never consults `TZ`. ICU's `uprv_tzname` under
`U_PLATFORM_USES_ONLY_WIN32_API` calls `uprv_detectWindowsTimeZone()` and does
not read the environment, so every zone is unsupported for that engine.
`setup` refuses the launcher unless `TIMEZONE_FALLBACK="host"`. This was
checked against ICU's Windows implementation, not by launching a browser on
Windows.

`-new-instance` is Unix-only and is omitted on Windows Firefox, where
`-no-remote` alone provides separate instances. Chromium profiles do not need
an equivalent flag: a distinct `--user-data-dir` is already a separate
process.

`-AppleLanguages (<locale>)` is not passed to Chromium on macOS. Chrome treats
the parenthesised value as a second navigation target (headless exits with
"Multiple targets are not supported"), and `--lang` is ignored there.
`navigator.languages` is still set. On Windows and Linux, `--lang` carries
`LOCALE` for the UI.

A running Chromium is detected from `SingletonLock` on POSIX, and only when
the recorded pid is alive, or from the byte-range lock on `lockfile` on
Windows. A stale lock left by a crash does not block the next Preferences
update.

The managed Chromium keys (`intl.accept_languages`, download directory,
`net.network_prediction_options`, `webrtc.ip_handling_policy`,
`profile.default_content_setting_values.geolocation`) are ordinary profile
preferences, not part of Chromium's tracked-pref set, so rewriting them does
not invalidate the Secure Preferences MAC. Proxy, WebRTC policy and
`navigator.languages` are also command-line switches, so they apply even when
the Preferences file was skipped.

## What is intentionally not provided

- VM/container security isolation: every profile runs as the same OS user
- OS-level GPS spoofing: only the Geolocation API is pinned, and only in
  Firefox. Chromium denies the permission when coordinates are configured
- Per-identity hardware fingerprints: one machine, so canvas/WebGL/font
  characteristics are shared. Firefox's `privacy.fingerprintingProtection`
  mitigates this but does not give each identity a distinct, plausible
  device. Chrome, Edge and Chromium have no equivalent switch. Brave Shields
  stay at their default
- Proxy authentication: neither Firefox preferences nor the Chromium
  `--proxy-server` switch carry credentials, so an upstream proxy that
  requires a user and password needs a local relay
- A per-process UI locale for Chromium on macOS
