"""Generate the Web Bot Auth signing key, its public JWK, and the directory.

    uv run python scripts/wba_keygen.py --out data/threedecks/wba [--force]

Writes ``private.pem`` (never commit it: ``data/`` is gitignored), ``public.jwk``
and ``directory.json``, then prints the keyid and the hosting/registration
steps. Hosting the directory and registering it with Cloudflare are manual
steps; see ``docs/plans/threedecks-anti-bot-research.md`` section 3.4.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from threedecks.wba import directory_document, jwk_from_private, thumbprint


def generate(out_dir: Path, force: bool = False) -> dict:
    """Write the key material; returns the public JWK. Raises if it exists."""
    private_path = out_dir / "private.pem"
    if private_path.exists() and not force:
        raise FileExistsError(private_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    jwk = jwk_from_private(key)
    (out_dir / "public.jwk").write_text(json.dumps(jwk, indent=2) + "\n", encoding="utf-8")
    (out_dir / "directory.json").write_text(
        json.dumps(directory_document(jwk), indent=2) + "\n", encoding="utf-8"
    )
    return jwk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="data/threedecks/wba", help="output directory")
    parser.add_argument("--force", action="store_true", help="overwrite an existing private.pem")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    try:
        jwk = generate(out_dir, args.force)
    except FileExistsError as exc:
        print(
            f"error: {exc} exists; pass --force to overwrite (the old key becomes useless)",
            file=sys.stderr,
        )
        return 1
    print(f"keyid:       {thumbprint(jwk)}")
    print(f"private key: {out_dir / 'private.pem'}  (gitignored; never commit it)")
    print(f"public JWK:  {out_dir / 'public.jwk'}")
    print(f"directory:   {out_dir / 'directory.json'}")
    print()
    print("Next steps:")
    print("1. Host the directory at https://<host>/.well-known/http-message-signatures-directory")
    print("   with Content-Type: application/http-message-signatures-directory+json;")
    print("   scripts/wba_directory.py emits a signed static response to paste.")
    print("2. Run the crawl with THREEDECKS_WBA_KEY pointing at private.pem and")
    print("   THREEDECKS_WBA_DIRECTORY at the hosted URL.")
    print("3. Cloudflare dashboard > Manage Account > Configurations > Bot Submission Form:")
    print("   Verification Method 'Request Signature', directory URL, UA dead-reckoning/0.1.")
    print("4. Confirm at https://crawltest.com/cdn-cgi/web-bot-auth (200 once registered).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
