"""Small admin commands: `python -m app.cli <command>`.

hash-password   read a password from stdin, print its argon2 hash for PASSWORD_HASH
openapi         write the API schema to openapi.json (the front end generates its types from it)
seed-demo       fill an empty database with the made-up demo data
import-legacy   load the first tracker's export into an empty database:
                  python -m app.cli import-legacy export.json [fx.json]
restore         load a backup (from Download backup, or /api/export) into an empty database:
                  python -m app.cli restore backup.json
"""

import getpass
import json
import sys
from collections.abc import Callable
from pathlib import Path

MIN_PASSWORD = 12


def hash_password(_args: list[str]) -> int:
    from app.auth import hash_password as argon2_hash

    password = sys.stdin.readline().rstrip("\n") if not sys.stdin.isatty() else getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD:
        print(f"Use at least {MIN_PASSWORD} characters.", file=sys.stderr)
        return 1
    print(argon2_hash(password))
    return 0


def openapi(_args: list[str]) -> int:
    from app.main import create_app

    Path("openapi.json").write_text(json.dumps(create_app().openapi(), indent=1) + "\n")
    print("wrote openapi.json")
    return 0


def seed_demo(_args: list[str]) -> int:
    from app.db import session_factory
    from app.demo import seed_demo as seed

    with session_factory()() as session:
        print(seed(session))
    return 0


def import_legacy(args: list[str]) -> int:
    from app.db import session_factory
    from app.legacy import ImportRefusedError
    from app.legacy import import_legacy as load

    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    export = json.loads(Path(args[0]).read_text())
    fx = json.loads(Path(args[1]).read_text()) if len(args) > 1 else None
    with session_factory()() as session:
        try:
            counts = load(session, export, fx)
        except ImportRefusedError as e:
            print(e, file=sys.stderr)
            return 1
    print(", ".join(f"{n} {name}" for name, n in counts.items()))
    return 0


def restore(args: list[str]) -> int:
    from app.backup import RestoreRefusedError
    from app.backup import restore as load
    from app.db import session_factory

    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    backup = json.loads(Path(args[0]).read_text())
    with session_factory()() as session:
        try:
            counts = load(session, backup)
        except RestoreRefusedError as e:
            print(e, file=sys.stderr)
            return 1
    print(", ".join(f"{n} {name}" for name, n in counts.items()))
    return 0


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "hash-password": hash_password,
    "openapi": openapi,
    "seed-demo": seed_demo,
    "import-legacy": import_legacy,
    "restore": restore,
}


def main(argv: list[str]) -> int:
    command = COMMANDS.get(argv[1] if len(argv) > 1 else "")
    if command is None:
        print(__doc__)
        return 2
    return command(argv[2:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
