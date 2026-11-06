"""User administration from the command line.

    python -m app.users_cli list
    python -m app.users_cli promote you@example.com        # make an existing account an administrator
    python -m app.users_cli set-password you@example.com   # choose a new password (typed, not shown)
"""

import sys
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import AppUser
from app.schemas.auth import RegisterRequest

COMMANDS = ("list", "promote", "set-password")


def check_password(email: str, password: str) -> str | None:
    """The same rules as registration. Returns a message, or None when the password is acceptable."""
    try:
        RegisterRequest(email=email, password=password)
    except ValidationError as e:
        return "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
    return None


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    with SessionLocal() as db:
        if sys.argv[1] == "list":
            for u in db.scalars(select(AppUser).order_by(AppUser.id)):
                print(f"{u.id:>4}  {u.role:<6} {u.email}")
            return
        if len(sys.argv) != 3:
            sys.exit(f"Usage: python -m app.users_cli {sys.argv[1]} <email>")
        user = db.scalar(select(AppUser).where(AppUser.email == sys.argv[2].strip().lower()))
        if user is None:
            sys.exit(f"No account with email {sys.argv[2]}. Run 'python -m app.users_cli list' to see the accounts.")
        if sys.argv[1] == "promote":
            user.role = "admin"
            db.commit()
            print(f"{user.email} is now an administrator.")
            return
        # set-password: typed twice, never echoed, never passed on the command line (it would stay in the shell history)
        password = getpass("New password: ")
        problem = check_password(user.email, password)
        if problem:
            sys.exit(f"Password not changed: {problem}")
        if getpass("Type it again: ") != password:
            sys.exit("Password not changed: the two entries are different.")
        user.password_hash = hash_password(password)
        db.commit()
        print(f"Password changed for {user.email}. Log in with the new password.")


if __name__ == "__main__":
    main()
