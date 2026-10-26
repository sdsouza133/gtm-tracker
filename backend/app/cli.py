"""Small admin commands: `python -m app.cli <command>`.

hash-password   read a password from stdin, print its argon2 hash for PASSWORD_HASH
openapi         write the API schema to openapi.json (the front end generates its types from it)
seed-demo       fill an empty database with the made-up demo data
"""

import getpass
import json
import sys
from pathlib import Path

MIN_PASSWORD = 12


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "hash-password":
        from app.auth import hash_password

        password = sys.stdin.readline().rstrip("\n") if not sys.stdin.isatty() else getpass.getpass("Password: ")
        if len(password) < MIN_PASSWORD:
            print(f"Use at least {MIN_PASSWORD} characters.", file=sys.stderr)
            return 1
        print(hash_password(password))
        return 0
    if command == "openapi":
        from app.main import create_app

        Path("openapi.json").write_text(json.dumps(create_app().openapi(), indent=1) + "\n")
        print("wrote openapi.json")
        return 0
    if command == "seed-demo":
        from app.db import session_factory
        from app.demo import seed_demo

        with session_factory()() as session:
            print(seed_demo(session))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
