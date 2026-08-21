#!/usr/bin/env python3
import argparse
import json

from app.database import get_session_factory
from app.services.server_admin import rotate_server_secret


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate an RDP Session Agent secret.")
    parser.add_argument("--server-id", required=True)
    args = parser.parse_args()

    with get_session_factory()() as db:
        try:
            secret = rotate_server_secret(db, args.server_id)
        except ValueError as exc:
            parser.error(str(exc))

    print(
        json.dumps(
            {
                "server_id": args.server_id,
                "agent_secret": secret,
                "warning": "Previous active credentials were revoked. Store the new secret securely.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
