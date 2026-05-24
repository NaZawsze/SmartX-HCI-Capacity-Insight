import argparse
import getpass
import sys

from app.db import init_db
from app.services.users import reset_password


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset-password", help="Reset a platform user password.")
    reset_parser.add_argument("--username", "-u", default="admin", help="Platform username. Defaults to admin.")
    reset_parser.add_argument("--password", "-p", help="New password. If omitted, prompts interactively.")

    args = parser.parse_args()
    if args.command == "reset-password":
        return _reset_password(args.username, args.password)
    parser.print_help()
    return 1


def _reset_password(username: str, password: str | None) -> int:
    init_db()
    next_password = password
    if next_password is None:
        next_password = getpass.getpass("New password: ")
        confirm_password = getpass.getpass("Confirm password: ")
        if next_password != confirm_password:
            print("Passwords do not match.", file=sys.stderr)
            return 2
    if not next_password:
        print("Password cannot be empty.", file=sys.stderr)
        return 2
    if not reset_password(username, next_password):
        print(f"User not found: {username}", file=sys.stderr)
        return 1
    print(f"Password reset for user: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
