from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from .config import Settings
from .connectivity import ConnectivityChecker
from .gateway import UnifiedGatewayClient


async def _run() -> int:
    parser = argparse.ArgumentParser(description="TMHI watchdog diagnostic commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("connectivity", help="Run the configured internet probes")
    subparsers.add_parser("gateway-test", help="Test gateway reachability and login")
    reboot_parser = subparsers.add_parser("reboot", help="Request a gateway reboot")
    reboot_parser.add_argument("--yes", action="store_true", help="Confirm the reboot")

    args = parser.parse_args()
    settings = Settings.from_env()
    checker = ConnectivityChecker(
        settings.probe_urls,
        settings.probe_timeout_seconds,
        settings.minimum_successful_probes,
    )
    gateway = UnifiedGatewayClient(
        settings.gateway_base_url,
        settings.gateway_username,
        settings.gateway_password,
        settings.gateway_timeout_seconds,
        settings.gateway_user_agent,
    )
    try:
        if args.command == "connectivity":
            result = await checker.check()
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.online else 2

        if args.command == "gateway-test":
            reachable = await gateway.is_reachable()
            output = {"reachable": reachable, "authenticated": False}
            if reachable:
                await gateway.authenticate()
                output["authenticated"] = True
            print(json.dumps(output, indent=2))
            return 0 if output["authenticated"] else 2

        if args.command == "reboot":
            if not args.yes:
                print("Refusing to reboot without --yes", file=sys.stderr)
                return 2
            if settings.dry_run:
                print("DRY_RUN=true: no reboot request was sent")
                return 0
            result = await gateway.reboot()
            print(json.dumps(asdict(result), indent=2))
            return 0 if result.accepted else 2

        return 2
    finally:
        await checker.close()
        await gateway.close()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
