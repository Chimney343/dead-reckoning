"""Web Bot Auth: sign requests so Cloudflare can verify who the crawler is.

This is honest identity, not evasion (rule 2): an Ed25519 key signs each
request with HTTP Message Signatures (RFC 9421), the public key is published in
a directory on a domain we control (draft-meunier-http-message-signatures-
directory-03), and the User-Agent still says plainly what the crawler is.

Everything is off until ``THREEDECKS_WBA_KEY`` (a PEM path) and
``THREEDECKS_WBA_DIRECTORY`` (an https URL) are both set, so the default crawl
carries no signing overhead.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)

TAG = "web-bot-auth"
DIRECTORY_TAG = "http-message-signatures-directory"


def b64url(data: bytes) -> str:
    """Base64url without padding, as JWK members and thumbprints use it."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def thumbprint(jwk: dict) -> str:
    """The RFC 7638 JWK thumbprint of an Ed25519 key (RFC 8037, Appendix A.3).

    The canonical form is the three public members in lexicographic order
    ("crv", "kty", "x"), no whitespace, no other members.
    """
    canonical = f'{{"crv":"{jwk["crv"]}","kty":"{jwk["kty"]}","x":"{jwk["x"]}"}}'.encode("ascii")
    return b64url(hashlib.sha256(canonical).digest())


def load_private_key(path: Path | str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return key


def jwk_from_private(key: Ed25519PrivateKey) -> dict:
    """The public JWK for the key, with its thumbprint as ``kid``."""
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw)}
    jwk["kid"] = thumbprint(jwk)
    jwk["use"] = "sig"
    return jwk


def directory_document(jwk: dict) -> dict:
    """A key-directory document (a JWKS) holding one public key."""
    return {"keys": [jwk]}


def sign_request(
    request,
    key: Ed25519PrivateKey,
    directory_url: str,
    *,
    created: float | None = None,
    nonce: str | None = None,
    expires_secs: int = 120,
) -> None:
    """Add the three Web Bot Auth headers to a Scrapy Request, in place.

    ``created``, ``nonce`` and ``expires_secs`` are injectable so tests can pin
    every byte; production keeps ``expires`` short (Cloudflare's replay
    protection) and lets the nonce be random.
    """
    if urlparse(directory_url).scheme != "https":
        raise ValueError(f"the directory URL must be https, got {directory_url!r}")
    created = int(time.time() if created is None else created)
    expires = created + int(expires_secs)
    nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii") if nonce is None else nonce
    agent = f'"{directory_url}"'  # an sf-string: quoted, per the directory draft
    # Serialize the parameters once and use these exact bytes in both the header
    # and the signature base: re-serializing them risks a subtle byte mismatch.
    params = (
        f'sig1=("@authority" "signature-agent")'
        f";created={created}"
        f';keyid="{thumbprint(jwk_from_private(key))}"'
        f';alg="ed25519"'
        f";expires={expires}"
        f';nonce="{nonce}"'
        f';tag="{TAG}"'
    )
    authority = urlparse(request.url).netloc  # as sent in Host
    base = "\n".join(
        [
            f'"@authority": {authority}',
            f'"signature-agent": {agent}',
            f'"@signature-params": {params}',
        ]
    ).encode("ascii")
    request.headers["Signature-Agent"] = agent
    request.headers["Signature-Input"] = params
    request.headers["Signature"] = f"sig1=:{base64.b64encode(key.sign(base)).decode()}:"


class WebBotAuthMiddleware:
    """Sign every request that goes to the wire; cache replays never get here."""

    def __init__(self, key: Ed25519PrivateKey, directory_url: str, expires_secs: int = 120):
        self.key = key
        self.directory_url = directory_url
        self.expires_secs = expires_secs
        self._logged = False

    @classmethod
    def from_crawler(cls, crawler):
        key_path = crawler.settings.get("THREEDECKS_WBA_KEY")
        directory_url = crawler.settings.get("THREEDECKS_WBA_DIRECTORY")
        if not key_path or not directory_url:
            raise NotConfigured  # identity is opt-in until a directory is hosted
        return cls(
            load_private_key(key_path),
            directory_url,
            crawler.settings.getint("THREEDECKS_WBA_EXPIRES_SECS", 120),
        )

    def process_request(self, request, spider=None):
        sign_request(request, self.key, self.directory_url, expires_secs=self.expires_secs)
        if not self._logged:
            self._logged = True
            logger.info("Web Bot Auth: signing requests for %s", self.directory_url)
        return None
