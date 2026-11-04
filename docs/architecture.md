# Architecture

## Layers

1. Firefox installation: one copy only, located per platform and launched
   natively on Apple Silicon
2. Profile: primary identity/data boundary
3. `identities/*.conf`: the single declarative source for one identity, shared
   between machines
4. `mif/`: cross-platform core, shared by macOS and Windows
5. `user.js`: language, geolocation, leak prevention, fingerprint protection,
   download path, proxy route
6. `TZ` environment variable: web-visible timezone, read by Firefox through ICU
7. Launcher: `.app` bundle on macOS, `.lnk` shortcut on Windows

`user.js` is regenerated on every launch, so the conf file always wins over
anything changed in `about:config`.

## Module layout

| Module | Responsibility |
| --- | --- |
| `mif/config.py` | Parse `identities/*.conf`, resolve per-identity paths |
| `mif/ffpath.py` | Find the Firefox executable, detect the arm64 slice |
| `mif/tz.py` | Timezone resolution and the Windows whitelist |
| `mif/prefs.py` | Render `user.js` from the template |
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
- Firefox preferences
- Proxy configuration

## What is made regionally consistent

- Public IP (proxy exit)
- Timezone (`TZ`, subject to the Windows limitation below)
- Language and locale (`intl.*`)
- Geolocation API coordinates (`geo.provider.network.url`)

## Leak paths that are closed

- Proxy failure falling back to a direct connection
- WebRTC ICE candidate enumeration
- DNS prefetch and the network predictor

## Platform constraints

Firefox only honours a fixed set of `TZ` values on Windows, enforced by
`IsOlsonCompatibleWindowsTimeZoneId` in `js/src/vm/DateTime.cpp`. Zones outside
that set are silently ignored in favour of the host timezone. `mif/tz.py` maps
the zones whose DST rules match the POSIX aliases and refuses to generate a
launcher for the rest, unless the identity opts in with
`TIMEZONE_FALLBACK="host"`. The refusal happens at `setup` time because a GUI
launcher has no console to print a warning to.

`-new-instance` is Unix-only and is omitted on Windows, where `-no-remote`
alone provides separate instances.

## What is intentionally not provided

- VM/container security isolation: every profile runs as the same OS user
- OS-level GPS spoofing: only the Geolocation API is pinned
- Per-identity hardware fingerprints: one machine, so canvas/WebGL/font
  characteristics are shared. `privacy.fingerprintingProtection` mitigates this
  but does not give each identity a distinct, plausible device.
- Proxy authentication: Firefox preferences cannot carry credentials, so
  upstream proxies requiring user/password need a local relay.
