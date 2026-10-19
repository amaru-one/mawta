"""Generate a signing key pair for the director's chat token (GET /auth/chat-token): the seed goes
to mawta-api, the public key to the chat service. It prints a secret, so run it locally and copy
the values into /srv/mawta/.env by hand.

Rotation: generate a pair with a new --kid, add its public key to the chat service next to the old
one, switch mawta-api to the new seed and key id, and remove the old public key once the old tokens
have expired (CHAT_TOKEN_TTL, 1h by default).
"""

import argparse
import json
import sys

from chattoken import generate_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatkey", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "-kid", "--kid", required=True, help="key id written in the token header, e.g. k1"
    )
    args = parser.parse_args(argv)
    seed, public = generate_key()
    print("# mawta-api (/srv/mawta/.env) — secret, never share or commit")
    print(f"CHAT_TOKEN_KEY_ID={args.kid}")
    print(f"CHAT_TOKEN_SIGNING_KEY={seed}")
    print()
    print("# chat service — public key, safe to share")
    print("CHAT_TOKEN_PUBLIC_KEYS=" + json.dumps({args.kid: public}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
