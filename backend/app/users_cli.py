"""User administration from the command line.

    python -m app.users_cli promote you@example.com    # make an existing account an administrator
    python -m app.users_cli list
"""

import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AppUser


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("promote", "list"):
        sys.exit(__doc__)
    with SessionLocal() as db:
        if sys.argv[1] == "list":
            for u in db.scalars(select(AppUser).order_by(AppUser.id)):
                print(f"{u.id:>4}  {u.role:<6} {u.email}")
            return
        if len(sys.argv) != 3:
            sys.exit("Usage: python -m app.users_cli promote <email>")
        user = db.scalar(select(AppUser).where(AppUser.email == sys.argv[2].strip().lower()))
        if user is None:
            sys.exit(f"No account with email {sys.argv[2]}. Register first via POST /api/v1/auth/register.")
        user.role = "admin"
        db.commit()
        print(f"{user.email} is now an administrator.")


if __name__ == "__main__":
    main()
