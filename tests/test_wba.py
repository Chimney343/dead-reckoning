"""Phase H: Web Bot Auth signing (RFC 9421; Cloudflare Web Bot Auth).

The signing base is byte-exact: the golden test rebuilds it from the spec text
by hand and verifies the signature against it, so a serialization drift fails.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scrapy.exceptions import NotConfigured
from scrapy.http import Request
from scrapy.utils.request import RequestFingerprinter
from scrapy.utils.test import get_crawler
from threedecks.wba import (
    WebBotAuthMiddleware,
    directory_document,
    jwk_from_private,
    load_private_key,
    sign_request,
    thumbprint,
)

import scripts.wba_directory as wba_directory
import scripts.wba_keygen as wba_keygen

# RFC 8037, Appendix A.1: the standard Ed25519 test key (test-only, published).
KEY = Ed25519PrivateKey.from_private_bytes(
    bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
)
RFC_X = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"
RFC_KID = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
DIRECTORY = "https://example.org/.well-known/http-message-signatures-directory"
URL = "https://threedecks.org/index.php?display_type=show_ship&id=1"

CREATED = 1_750_000_000
NONCE = "dGVzdC1ub25jZQ=="


def test_thumbprint_matches_rfc_8037():
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": RFC_X}
    assert thumbprint(jwk) == RFC_KID


def test_thumbprint_matches_the_cloudflare_documentation_pair():
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"}
    assert thumbprint(jwk) == "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"


def test_jwk_from_private_carries_the_public_key_and_kid():
    jwk = jwk_from_private(KEY)
    assert (jwk["kty"], jwk["crv"], jwk["x"]) == ("OKP", "Ed25519", RFC_X)
    assert jwk["kid"] == RFC_KID
    assert jwk["use"] == "sig"


# The signing base for the golden test, written out by hand from RFC 9421 §2.5
# and the Cloudflare header examples. If sign_request's serialization drifts,
# the signature no longer matches this base.
GOLDEN_INPUT = (
    'sig1=("@authority" "signature-agent")'
    f';created={CREATED};keyid="{RFC_KID}";alg="ed25519";expires={CREATED + 120}'
    f';nonce="{NONCE}";tag="web-bot-auth"'
)
GOLDEN_BASE = (
    '"@authority": threedecks.org\n'
    f'"signature-agent": "{DIRECTORY}"\n'
    f'"@signature-params": {GOLDEN_INPUT}'
).encode("ascii")
GOLDEN_SIGNATURE = base64.b64encode(KEY.sign(GOLDEN_BASE)).decode("ascii")


def test_signer_headers_are_byte_exact():
    request = Request(URL)
    sign_request(request, KEY, DIRECTORY, created=CREATED, nonce=NONCE, expires_secs=120)
    assert request.headers["Signature-Agent"] == f'"{DIRECTORY}"'.encode()
    assert request.headers["Signature-Input"] == GOLDEN_INPUT.encode()
    assert request.headers["Signature"] == f"sig1=:{GOLDEN_SIGNATURE}:".encode()
    # Round trip: the public key verifies the signature over the hand-made base.
    KEY.public_key().verify(base64.b64decode(GOLDEN_SIGNATURE), GOLDEN_BASE)


def test_signer_requires_an_https_directory():
    with pytest.raises(ValueError):
        sign_request(Request(URL), KEY, "http://example.org/dir", created=CREATED, nonce=NONCE)


def write_key(tmp_path, name="private.pem"):
    path = tmp_path / name
    path.write_bytes(
        KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def test_middleware_is_off_without_settings(tmp_path):
    with pytest.raises(NotConfigured):
        WebBotAuthMiddleware.from_crawler(get_crawler())
    crawler = get_crawler(settings_dict={"THREEDECKS_WBA_KEY": str(write_key(tmp_path))})
    with pytest.raises(NotConfigured):
        WebBotAuthMiddleware.from_crawler(crawler)


def test_middleware_signs_without_changing_the_fingerprint(tmp_path):
    crawler = get_crawler(
        settings_dict={
            "THREEDECKS_WBA_KEY": str(write_key(tmp_path)),
            "THREEDECKS_WBA_DIRECTORY": DIRECTORY,
        }
    )
    middleware = WebBotAuthMiddleware.from_crawler(crawler)
    request, plain = Request(URL), Request(URL)
    middleware.process_request(request)
    assert request.headers["Signature-Agent"] == f'"{DIRECTORY}"'.encode()
    assert b"web-bot-auth" in request.headers["Signature-Input"]
    assert b'keyid="' + RFC_KID.encode() + b'"' in request.headers["Signature-Input"]
    assert request.headers["Signature"].startswith(b"sig1=:")
    # The cache keys requests by fingerprint, and fingerprints ignore headers:
    # enabling signing must not cause refetches.
    fingerprinter = RequestFingerprinter()
    assert fingerprinter.fingerprint(request) == fingerprinter.fingerprint(plain)


def test_middleware_signs_robots_txt_too(tmp_path):
    crawler = get_crawler(
        settings_dict={
            "THREEDECKS_WBA_KEY": str(write_key(tmp_path)),
            "THREEDECKS_WBA_DIRECTORY": DIRECTORY,
        }
    )
    middleware = WebBotAuthMiddleware.from_crawler(crawler)
    request = Request("https://threedecks.org/robots.txt")
    middleware.process_request(request)
    params = request.headers["Signature-Input"].decode()
    base = (
        '"@authority": threedecks.org\n'
        f'"signature-agent": "{DIRECTORY}"\n'
        f'"@signature-params": {params}'
    ).encode()
    signature = base64.b64decode(request.headers["Signature"][len(b"sig1=:") : -1])
    KEY.public_key().verify(signature, base)


def test_keygen_writes_a_matching_directory(tmp_path):
    out = tmp_path / "wba"
    jwk = wba_keygen.generate(out)
    private = load_private_key(out / "private.pem")
    assert jwk_from_private(private) == jwk
    assert json.loads((out / "public.jwk").read_text(encoding="utf-8")) == jwk
    assert json.loads((out / "directory.json").read_text(encoding="utf-8")) == {
        "keys": [jwk]
    }


def test_keygen_refuses_to_overwrite_without_force(tmp_path):
    out = tmp_path / "wba"
    wba_keygen.generate(out)
    pem = (out / "private.pem").read_bytes()
    with pytest.raises(FileExistsError):
        wba_keygen.generate(out)
    assert (out / "private.pem").read_bytes() == pem  # the old key survived
    assert wba_keygen.main(["--out", str(out)]) == 1
    assert (out / "private.pem").read_bytes() == pem
    swapped = wba_keygen.generate(out, force=True)
    assert jwk_from_private(load_private_key(out / "private.pem")) == swapped


def test_directory_response_headers_are_well_formed():
    created = CREATED
    headers, body = wba_directory.sign_directory_response(
        KEY, "directory.example.org", created=created, validity_secs=30 * 86400
    )
    assert headers["Content-Type"] == "application/http-message-signatures-directory+json"
    assert headers["Cache-Control"] == "max-age=86400"
    params = headers["Signature-Input"]
    assert params.startswith('sig1=("@authority";req)')
    assert f'keyid="{RFC_KID}"' in params
    assert 'tag="http-message-signatures-directory"' in params
    assert f"created={created}" in params
    assert f"expires={created + 30 * 86400}" in params
    base = f'"@authority";req: directory.example.org\n"@signature-params": {params}'.encode()
    signature = base64.b64decode(headers["Signature"].removeprefix("sig1=:").removesuffix(":"))
    KEY.public_key().verify(signature, base)
    assert json.loads(body) == directory_document(jwk_from_private(KEY))


@pytest.mark.network
def test_crawltest_accepts_the_format():
    # 401: well-formed, unknown key. 400 would be a formatting bug.
    request = Request("https://crawltest.com/cdn-cgi/web-bot-auth")
    sign_request(request, Ed25519PrivateKey.generate(), DIRECTORY)
    headers = {
        name: request.headers[name].decode()
        for name in ("Signature-Agent", "Signature-Input", "Signature")
    }
    response = httpx.get(request.url, headers=headers, follow_redirects=True, timeout=30.0)
    assert response.status_code == 401, f"{response.status_code}: {response.text[:500]}"
