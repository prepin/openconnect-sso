#!/usr/bin/env python3
"""Stop one OpenConnect tunnel started by the invoking sudo user."""

import os
import re
import signal
import sys
from pathlib import Path


def authorized_process(executable, owner, environment, arguments, uid, interface):
    """Allow only the requested root OpenConnect tunnel of the sudo user."""
    tunnel_argument = interface.encode()
    matches_interface = b"--interface=" + tunnel_argument in arguments or any(
        arguments[index : index + 2] == [b"--interface", tunnel_argument]
        for index in range(len(arguments) - 1)
    )
    return (
        executable == Path("/usr/bin/openconnect")
        and owner == 0
        and b"SUDO_UID=" + uid.encode() in environment
        and b"--cookie-on-stdin" in arguments
        and matches_interface
    )


def descendant_of(pid: int, ancestor: int) -> bool:
    """Only signal OpenConnect while its original worker is still running."""
    for _ in range(32):
        if pid == ancestor:
            return True
        try:
            status = (Path("/proc") / str(pid) / "status").read_text()
            pid = int(
                next(
                    line.split()[1]
                    for line in status.splitlines()
                    if line.startswith("PPid:")
                )
            )
        except (OSError, StopIteration, ValueError):
            return False
        if pid <= 1:
            return False
    return False


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        arguments = [b"/usr/bin/openconnect", b"--cookie-on-stdin", b"--interface=tun0"]
        assert authorized_process(
            Path("/usr/bin/openconnect"),
            0,
            [b"SUDO_UID=1000"],
            arguments,
            "1000",
            "tun0",
        )
        assert not authorized_process(
            Path("/usr/bin/openconnect"),
            0,
            [b"SUDO_UID=1000"],
            arguments,
            "1000",
            "other",
        )
        assert not authorized_process(
            Path("/usr/bin/kill"), 0, [b"SUDO_UID=1000"], arguments, "1000", "tun0"
        )
        return 0

    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        print("Usage: vpn-stop-helper <worker-pid|0> <interface>", file=sys.stderr)
        return 2

    worker_pid = int(sys.argv[1])
    interface = sys.argv[2]
    if worker_pid == 1 or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.+-]{0,14}", interface
    ):
        return 2

    sudo_uid = os.environ.get("SUDO_UID")
    if not sudo_uid or not sudo_uid.isdigit() or os.geteuid() != 0:
        print("Run this helper through sudo.", file=sys.stderr)
        return 1

    if worker_pid:
        try:
            worker = Path("/proc") / str(worker_pid)
            command = (worker / "cmdline").read_bytes().split(b"\0")
            if worker.stat().st_uid != int(sudo_uid) or not any(
                b"vpn-connect" in argument or b"openconnect-sso" in argument
                for argument in command
            ):
                raise ValueError("unrelated worker")
        except (OSError, ValueError):
            print("Refusing to stop an unrelated worker.", file=sys.stderr)
            return 1

    matches = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            executable = (process / "exe").resolve(strict=True)
            arguments = (process / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            environment = (process / "environ").read_bytes().split(b"\0")
            owner = process.stat().st_uid
        except (OSError, ValueError):
            continue
        if authorized_process(
            executable, owner, environment, arguments, sudo_uid, interface
        ) and (worker_pid == 0 or descendant_of(int(process.name), worker_pid)):
            matches.append(int(process.name))

    if not matches:
        return 3  # The worker may still be authenticating, or its tunnel has ended.
    if len(matches) != 1:
        print("Refusing to stop multiple tunnels.", file=sys.stderr)
        return 1
    try:
        os.kill(matches[0], signal.SIGINT)
    except ProcessLookupError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
