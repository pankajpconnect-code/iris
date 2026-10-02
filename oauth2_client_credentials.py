"""Client Credentials grant (RFC 6749 §4.4) token minting.

Mirrors run_api_from_csv.generate_token's sys.exit-on-failure idiom exactly
(same status-code message shape, same field-redaction rule) so every
existing mint call site's `except SystemExit` handling covers this mode
too, with no new exception type to teach them about.
"""
import sys

import requests


def mint_client_credentials_token(client_id, client_secret, token_url, scope, auth_style, timeout):
    form = {"grant_type": "client_credentials"}
    if scope:
        form["scope"] = scope
    kwargs = {"data": form, "timeout": timeout}
    if auth_style == "basic-header":
        kwargs["auth"] = (client_id, client_secret)
    else:
        form["client_id"] = client_id
        form["client_secret"] = client_secret

    resp = requests.post(token_url, **kwargs)
    if not resp.ok:
        sys.exit(f"OAuth2 token request failed: {resp.status_code} {resp.text[:500]}")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        redacted = {k: ("<redacted>" if "token" in k.lower() else v) for k, v in body.items()}
        sys.exit(f"OAuth2 token response missing 'access_token': {redacted}")
    return token
