"""Emit the signed Web Bot Auth key directory a host must serve.

    uv run python scripts/wba_directory.py --key data/threedecks/wba/private.pem
                                          --authority <host> [--validity-days 30]

Prints the JSON body and the response headers for the well-known URL
``/.well-known/http-message-signatures-directory``. The response is signed with
the crawler's own key over ``("@authority";req)`` and tagged
``http-message-signatures-directory``, so nobody can mirror the directory and
register as this crawler (draft-meunier-http-message-signatures-directory-03).

For static hosting the signature's ``created`` is now and ``expires`` is
``created`` plus the validity (default 30 days): host the bytes, and regenerate
and redeploy before they expire. A Worker that signs per request can use
:func:`sign_directory_response` instead.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys

from threedecks.wba import (
    DIRECTORY_TAG,
    directory_document,
    jwk_from_private,
    load_private_key,
    thumbprint,
)

CONTENT_TYPE = "application/http-message-signatures-directory+json"
CACHE_CONTROL = "max-age=86400"


def sign_directory_response(
    key, authority: str, *, created: float | None = None, validity_secs: int = 30 * 86400
) -> tuple[dict[str, str], str]:
    """The directory response: ``(headers, body)``, signed over the request's host."""
    import time

    created = int(time.time() if created is None else created)
    expires = created + int(validity_secs)
    # Serialized once and reused byte-for-byte in the header and the base string.
    params = (
        'sig1=("@authority";req)'
        f";created={created}"
        f';keyid="{thumbprint(jwk_from_private(key))}"'
        f';alg="ed25519"'
        f";expires={expires}"
        f';tag="{DIRECTORY_TAG}"'
    )
    base = "\n".join(
        [
            f'"@authority";req: {authority}',
            f'"@signature-params": {params}',
        ]
    ).encode("ascii")
    headers = {
        "Content-Type": CONTENT_TYPE,
        "Cache-Control": CACHE_CONTROL,
        "Signature-Input": params,
        "Signature": f"sig1=:{base64.b64encode(key.sign(base)).decode()}:",
    }
    body = json.dumps(directory_document(jwk_from_private(key)), indent=2) + "\n"
    return headers, body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--key", required=True, help="the signing private key (PEM)")
    parser.add_argument("--authority", required=True, help="the Host the directory is served at")
    parser.add_argument(
        "--validity-days", type=float, default=30, help="how long the static signature lasts"
    )
    args = parser.parse_args(argv)
    key = load_private_key(args.key)
    headers, body = sign_directory_response(
        key, args.authority, validity_secs=int(args.validity_days * 86400)
    )
    sys.stdout.write(body)
    sys.stdout.write("\n--- response headers ---\n")
    for name, value in headers.items():
        sys.stdout.write(f"{name}: {value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
