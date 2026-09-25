"""Starting and inspecting an Aworg."""

from __future__ import annotations

import argparse
import socket
import sys

from . import auth
from .install import describe, ensure_installed, install
from .paths import Paths, resolve_home
from .secrets import SecretStore


def new_password(paths: Paths) -> str:
    """Make one, write down its hash, and hand back the only copy.

    The only copy, and that is the point of hashing it: what goes in the
    store cannot be turned back into this string, so this is the one moment
    it exists. See auth.py.
    """
    fresh = auth.generate()
    auth.store(SecretStore(paths.secrets_db), fresh)
    return fresh


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
    commands.add_parser(
        "password",
        help="Set a new password for the owner interface, and print it",
    )

    args = parser.parse_args(argv)
    paths = Paths(resolve_home(args.home))

    if args.command == "home":
        print(paths.home)
        return 0

    if args.command == "password":
        paths.ensure()
        fresh = new_password(paths)
        print("A new password for this Aworg's interface:")
        print()
        print(f"    {fresh}")
        print()
        print("Anyone signed in has been signed out.")
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

        # Made on first start rather than at install, so that an Aworg
        # installed months ago and started today still gets one -- and so
        # that the moment it is printed is the moment somebody is looking
        # at a terminal waiting for an address.
        fresh = None
        if not auth.is_set(SecretStore(paths.secrets_db)):
            fresh = new_password(paths)

        print(f"AWORG home     {paths.home}")
        print(f"Interface      http://{host}:{port}")
        if fresh:
            print(f"Password       {fresh}")
        print()
        if fresh:
            print("That password is shown once and is not stored in a form")
            print("anything can read back. If it is lost:  aworg password")
            print()
        print("Open that address in a browser.")
        # Said plainly, because the difference is the whole security model:
        # on loopback the only things that can reach this are already
        # running as the owner, and on any other address that is no longer
        # true. Not a warning -- binding wider is a legitimate thing to do
        # and the password is what makes it so -- but it should be a
        # decision somebody made rather than one they discover.
        if host not in ("127.0.0.1", "localhost", "::1"):
            print()
            print(f"Reachable from the network on {host}. The password is all")
            print("that stands in front of a Resident with shell access, so")
            print("keep this on a network you trust.")
        print()
        # The address is decided here, so it is told here. An application
        # the Resident starts is given this to report to, and AWORG cannot
        # work it out from the inside -- a server does not know what anyone
        # called it.
        # Built here rather than left to uvicorn.run, which is exactly this
        # and throws the Server away. Keeping it is what lets the last line
        # below tell a clean stop from a forced one.
        config = uvicorn.Config(
            create_app(paths, address=f"http://{host}:{port}"),
            host=host, port=port, log_level="warning",
            # Why one Ctrl-C was not enough.
            #
            # uvicorn's default here is None, meaning wait for every open
            # connection forever. Two of AWORG's endpoints never close on
            # their own -- the Activity feed is `while True: await
            # queue.get()`, and the turn stream lives as long as the turn --
            # so an owner with the interface open in a browser had a server
            # that began shutting down and then waited on a connection that
            # was never going to end. The only way out was a second Ctrl-C,
            # which is uvicorn's force quit and skips the rest of shutdown.
            #
            # Three seconds: long enough for a real request to finish, short
            # enough that stopping an Aworg feels like stopping anything
            # else. Past it, uvicorn cancels what is left, the generators'
            # finally blocks run, and the lifespan shutdown proceeds
            # normally -- so the programs the Resident started are still
            # stopped properly.
            timeout_graceful_shutdown=3,
        )
        server = uvicorn.Server(config)
        try:
            server.run()
        except KeyboardInterrupt:
            # **Not** how the shutdown happens. uvicorn installs its own
            # handler for SIGINT, sets should_exit, and unwinds gracefully
            # on its own -- by the time anything arrives here, that has
            # already finished.
            #
            # This is here because of what uvicorn does *afterwards*: having
            # shut down because of a signal, it restores the original
            # handler and re-raises the signal, so the process exits the way
            # a program interrupted by Ctrl-C conventionally does. With the
            # default handler back in place that is a KeyboardInterrupt, and
            # an owner who pressed Ctrl-C got a stack trace at the end of a
            # shutdown that had in fact gone perfectly.
            pass

        if server.force_exit:
            # A second Ctrl-C, which uvicorn treats as "stop arguing and
            # quit". The graceful path was abandoned part way, so this must
            # not claim otherwise -- the Resident's programs may still be
            # running, and saying so is the difference between a message and
            # a reassurance.
            print("AWORG was forced to stop. Programs it started may still "
                  "be running.")
        else:
            # The lifespan has run: the followers are cancelled, the log is
            # written, and the Resident's programs are stopped.
            print("AWORG stopped.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
