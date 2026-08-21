#!/usr/bin/env python3
import argparse
import json

from app.database import get_session_factory
from app.services.server_admin import register_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Register an RDP Session Agent server.")
    parser.add_argument("--hostname")
    parser.add_argument("--fqdn")
    parser.add_argument("--os-version")
    args = parser.parse_args()

    with get_session_factory()() as db:
        server, secret = register_server(
            db,
            hostname=args.hostname,
            fqdn=args.fqdn,
            os_version=args.os_version,
        )

    print(
        json.dumps(
            {
                "server_id": server.id,
                "agent_secret": secret,
                "warning": "Store the agent secret securely; the API stores only its hash.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
