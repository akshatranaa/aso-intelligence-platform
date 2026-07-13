"""One-time backfill: assign every existing target app to a user.

Apps collected before per-user ownership existed have no owner, so they won't
appear under any account. Run this once, after creating your Supabase account,
to claim all of them:

    DATABASE_URL=... python3 scripts/backfill_user_apps.py <your-supabase-user-uuid>

Find your user UUID in the Supabase dashboard → Authentication → Users.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

import database  # noqa: E402  (must load env before importing)


def main(user_id: str) -> None:
    """Link every target app to the given Supabase user."""
    database.create_tables()
    apps = [a for a in database.get_all_apps() if a.get("is_target_app") == 1]
    for app in apps:
        database.add_user_app(user_id, app["app_id"])
    print(f"Assigned {len(apps)} app(s) to user {user_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/backfill_user_apps.py <supabase-user-uuid>")
        sys.exit(1)
    main(sys.argv[1])
