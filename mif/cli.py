"""Command line entry point: setup, launch, status, new-identity, wipe, install."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import launchers, prefs, tz
from .config import (
    APPS_DIR,
    DATA_DIR,
    IDENTITIES_DIR,
    Identity,
    MifError,
    all_identities,
    load_identity,
    validate_name,
)
from .ffpath import firefox_binary, is_windows, wants_arm64_launch

NEW_CONF = """NAME="{name}"
LANGUAGE="{language}"
LOCALE="{locale}"
TIMEZONE="{timezone}"
PROXY_TYPE="{proxy_type}"
PROXY_HOST="{proxy_host}"
PROXY_PORT="{proxy_port}"
GEO_LAT="{lat}"
GEO_LON="{lon}"
# Set to false if a site breaks under canvas/screen/font normalisation.
FINGERPRINT_PROTECTION="true"
TEMPORARY="false"
"""


def _resolve_timezone(identity: Identity) -> tz.Resolution:
    """Resolve the timezone, refusing to silently fall back to the host one."""
    resolution = tz.resolve(identity.timezone)
    if not resolution.supported and identity.timezone_fallback != "host":
        raise MifError(tz.unsupported_message(identity.name, resolution))
    return resolution


def _prepare(identity: Identity) -> tz.Resolution:
    resolution = _resolve_timezone(identity)
    prefs.write(identity, resolution)
    return resolution


def cmd_setup(args: argparse.Namespace) -> int:
    firefox_binary()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APPS_DIR.mkdir(parents=True, exist_ok=True)

    identities = all_identities()
    if not identities:
        raise MifError(f"No identities found in {IDENTITIES_DIR}")

    failures: list[str] = []
    for identity in identities:
        try:
            resolution = _prepare(identity)
        except MifError as error:
            failures.append(str(error))
            launchers.remove(identity.name)
            continue
        launchers.create(identity)
        note = ""
        if resolution.substituted:
            note = f"  (timezone applied as {resolution.value})"
        elif not resolution.supported:
            note = "  (host timezone, TIMEZONE_FALLBACK=host)"
        print(f"Prepared {identity.name} -> {identity.profile_dir}{note}")

    if failures:
        print("", file=sys.stderr)
        for failure in failures:
            print(f"REFUSED: {failure}\n", file=sys.stderr)

    print()
    print(f"Launchers are in: {APPS_DIR}")
    print("Timezone, locale and geolocation are applied from the identity configs.")
    print("No companion extensions are needed; remove any Spoof Timezone / Spoof")
    print("Geolocation add-ons left over from earlier versions.")

    return 1 if failures else 0


def cmd_status(args: argparse.Namespace) -> int:
    identities = all_identities()
    if not identities:
        raise MifError(f"No identities found in {IDENTITIES_DIR}")

    print(f"Platform: {sys.platform}")
    try:
        print(f"Firefox:  {firefox_binary()}")
    except MifError as error:
        print(f"Firefox:  NOT FOUND ({error.args[0].splitlines()[0]})")
    print()

    width = max(len(i.name) for i in identities)
    for identity in identities:
        resolution = tz.resolve(identity.timezone)
        if resolution.supported:
            state = "ok"
        elif identity.timezone_fallback == "host":
            state = "host timezone (acknowledged)"
        else:
            state = "REFUSED - see mif setup"
        geo = (
            f"{identity.geo_lat},{identity.geo_lon}"
            if identity.geo_lat
            else "not pinned"
        )
        proxy = (
            f"{identity.proxy_type}://{identity.proxy_host}:{identity.proxy_port}"
            if identity.proxy_type != "none"
            else "direct"
        )
        print(f"{identity.name:<{width}}  tz={resolution.summary}  [{state}]")
        print(f"{'':<{width}}  proxy={proxy}  geo={geo}")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    resolution = _prepare(identity)
    binary = firefox_binary()

    env = dict(os.environ)
    if resolution.value:
        env["TZ"] = resolution.value
    else:
        env.pop("TZ", None)

    command: list[str] = []
    if wants_arm64_launch(binary):
        command += ["/usr/bin/arch", "-arm64"]
    command.append(str(binary))
    command.append("-no-remote")
    if not is_windows():
        # -new-instance is Unix-only; passing it on Windows is not supported.
        command.append("-new-instance")
    command += ["-profile", str(identity.profile_dir)]
    command += args.args

    if is_windows():
        subprocess.Popen(command, env=env, close_fds=True)
        return 0
    os.execve(command[0], command, env)


def cmd_new_identity(args: argparse.Namespace) -> int:
    name = validate_name(args.name)
    conf = IDENTITIES_DIR / f"{name}.conf"
    if conf.exists() and not args.force:
        raise MifError(f"{conf} already exists (pass --force to overwrite)")
    IDENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        NEW_CONF.format(
            name=name,
            language=args.language,
            locale=args.locale,
            timezone=args.timezone,
            proxy_type=args.proxy_type,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            lat=args.latitude,
            lon=args.longitude,
        )
    )
    print(f"Created {conf}")
    return cmd_setup(args)


def cmd_wipe(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    if not identity.temporary:
        raise MifError(
            f"{identity.name} is not marked TEMPORARY=true; refusing to wipe it."
        )
    for path in (identity.profile_dir, identity.download_dir):
        if path.exists():
            shutil.rmtree(path)
    print(f"Wiped temporary identity: {identity.name}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    status = cmd_setup(args)
    destinations = launchers.install_destinations()
    if not destinations:
        raise MifError(f"No install location known for platform {sys.platform!r}")

    sources = sorted(p for p in APPS_DIR.iterdir() if p.suffix in (".app", ".lnk"))
    if not sources:
        raise MifError(f"No launchers found in {APPS_DIR}; run setup first.")

    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = destination / source.name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        print(f"Installed {len(sources)} launcher(s) to: {destination}")
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mif", description="Multi-identity Firefox launcher."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Regenerate profiles and launchers")
    setup.set_defaults(func=cmd_setup)

    status = sub.add_parser("status", help="Show the effective state per identity")
    status.set_defaults(func=cmd_status)

    launch = sub.add_parser("launch", help="Launch one identity")
    launch.add_argument("identity")
    launch.add_argument("args", nargs=argparse.REMAINDER, help="Extra Firefox args")
    launch.set_defaults(func=cmd_launch)

    new = sub.add_parser("new-identity", help="Create a new identity config")
    new.add_argument("name")
    new.add_argument("language")
    new.add_argument("locale")
    new.add_argument("timezone")
    new.add_argument("latitude")
    new.add_argument("longitude")
    new.add_argument("proxy_type", nargs="?", default="none")
    new.add_argument("proxy_host", nargs="?", default="")
    new.add_argument("proxy_port", nargs="?", default="")
    new.add_argument("--force", action="store_true")
    new.set_defaults(func=cmd_new_identity)

    wipe = sub.add_parser("wipe", help="Erase a TEMPORARY identity's data")
    wipe.add_argument("identity")
    wipe.set_defaults(func=cmd_wipe)

    install = sub.add_parser("install", help="Copy launchers to the desktop/menu")
    install.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MifError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
