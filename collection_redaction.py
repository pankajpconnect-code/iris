"""Secret redaction for collection export (v2.1 schema).

Split out of collection_io.py, which had grown past this repo's 500-line
file-size gate — to_collection (collection_io.py) is the only caller of the
three public functions here, so the split carries no other call-site changes.
"""

import re

import collection_store

_FULL_VAR_RE = re.compile(r"^\{\{\s*[^{}]+?\s*\}\}$")


def _is_literal_value(value):
    return not _FULL_VAR_RE.match(str(value or "").strip())


# A {{var}} reference is a pointer, not a secret — it resolves locally at send
# time from Keychain/env storage (itself already redacted, see
# collection_store._SECRET_NAME_RE). A literal value under a secret-named key
# is the actual credential and must never leave the machine in an export.
def _is_literal_secret(key, value):
    if not collection_store._SECRET_NAME_RE.search(key or ""):
        return False
    return _is_literal_value(value)


# Our own translated auth shape's field names are fixed by our schema (not
# arbitrary user-chosen strings like header/param keys), so the actual secret
# fields are named explicitly here rather than matched by
# collection_store._SECRET_NAME_RE — that pattern doesn't cover apiKeyValue,
# and would wrongly flag non-secret fields like refreshTokenCookieName.
_AUTH_SECRET_FIELDS = {"bearerToken", "basicPassword", "apiKeyValue", "oauth2ClientSecret", "refreshToken"}


def redact_headers_for_export(headers):
    return [
        {**h, "value": "***"} if _is_literal_secret(h.get("key"), h.get("value")) else h
        for h in headers
    ]


def redact_body_params_for_export(params):
    """Same rule as redact_headers_for_export — a literal client secret in a
    urlencoded body param is exactly as exposed as one in a header."""
    return [
        {**p, "value": "***"} if _is_literal_secret(p.get("key"), p.get("value")) else p
        for p in params
    ]


def redact_auth_for_export(auth):
    if not isinstance(auth, dict):
        return auth
    # Our own translated shape ({"mode": ..., "bearerToken": ...}) is flat —
    # the loop below assumes each value is a list of {key, value} entries
    # (the raw source collection format's auth shape), so it would silently
    # skip every field here and leak a literal bearerToken/basicPassword
    # into the export.
    if "mode" in auth:
        return {
            key: "***" if key in _AUTH_SECRET_FIELDS and _is_literal_value(value) else value
            for key, value in auth.items()
        }
    redacted = dict(auth)
    for auth_type, entries in auth.items():
        if not isinstance(entries, list):
            continue
        redacted[auth_type] = [
            {**e, "value": "***"} if isinstance(e, dict) and _is_literal_secret(e.get("key"), e.get("value")) else e
            for e in entries
        ]
    return redacted
