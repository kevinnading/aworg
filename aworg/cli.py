"""Starting and inspecting an Aworg."""

from __future__ import annotations

import argparse
import socket
import sys

from .install import describe, ensure_installed, install
from .paths import Paths, resolve_home


def port_in_use(host: str, port: int) -> bool:
    """Whether something already holds that port.

    Asked before uvicorn is started, because uvicorn's way of answering is
    an OSError and a stack trace, and the commonest reason for it is the
    least alarming one: an Aworg is already running.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            # The option uvicorn sets, so that this asks the same question
            # uvicorn is about to. Windows is excluded deliberately: there
            # SO_REUSEADDR lets a second socket bind over a live one, which
            # would make every port look free.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aworg",
        description="AWORG - Autonomous Workspace Organism",
    )
    parser.add_argument(
        "--home",
        help="Where this Aworg lives (default: $AWORG_HOME, or ~/.aworg)",
    )
    commands = parser.add_subparsers(dest="command")

    start = commands.add_parser(
        "start",
        # It prints the address rather than opening anything. Opening a
        # browser is per-OS work, and a promise in the help text that the
        # program does not keep is worse than no promise.
        help="Start the Aworg and print where its interface is",
    )
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8420)

    for name, help_text in (
        ("install", "Create this Aworg: its home, its databases, and the "
                    "skills, personas and capabilities AWORG ships"),
        # The old name for it, kept because it is in the docs and in
        # people's shell history, and because an installer that tells you
        # off for using last month's word is not a good first impression.
        ("init", "The same as install"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--workspace",
            help="Use this directory as the Living Workspace, rather than "
                 "workspace/ under the home. Made if it does not exist; "
                 "nothing already in it is touched.",
        )
        command.add_argument(
            "--with",
            dest="also",
            action="append",
            metavar="NAME",
            help="Also install a capability that is not installed by "
                 "default, such as chromium. May be given more than once.",
        )
        command.add_argument(
            "--force",
            action="store_true",
            help="Put every shipped skill, persona and capability back the "
                 "way it shipped, discarding changes made to them here.",
        )

    commands.add_parser("home", help="Print this Aworg's home directory")

    args = parser.parse_args(argv)
    paths = Paths(resolve_home(args.home))

    if args.command == "home":
        print(paths.home)
        return 0

    if args.command in ("install", "init"):
        print(describe(install(paths, force=args.force,
                               workspace=args.workspace,
                               also=args.also or ())))
        print()
        print("Start it with:  aworg start")
        return 0

    if args.command == "start" or args.command is None:
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8420)

        # Asked before anything is installed or created, so that a port
        # collision costs nothing and leaves nothing half done.
        if port_in_use(host, port):
            print(f"Port {port} is already in use on {host}.", file=sys.stderr)
            print(file=sys.stderr)
            print(
                f"If that is an Aworg, it is at  http://{host}:{port}",
                file=sys.stderr,
            )
            print(
                f"If it is something else:       aworg start --port {port + 1}",
                file=sys.stderr,
            )
            return 1

        # Starting an Aworg that was never installed installs it, once.
        # Never again after that, so that a persona the owner deleted stays
        # deleted -- see install.ensure_installed.
        first = ensure_installed(paths)
        paths.ensure()
        if first is not None:
            print(describe(first))
            print()

        import uvicorn

        from .server import create_app

        print(f"AWORG home     {paths.home}")
        print(f"Interface      http://{host}:{port}")
        print()
        print("Open that address in a browser.")
        print()
        # The address is decided here, so it is told here. An application
        # the Resident starts is given this to report to, and AWORG cannot
        # work it out from the inside -- a server does not know what anyone
        # called it.
        uvicorn.run(
            create_app(paths, address=f"http://{host}:{port}"),
            host=host, port=port, log_level="warning",
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
