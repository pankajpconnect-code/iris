#!/usr/bin/env python3
"""Generate a bearer token, then call one API endpoint once per row of a CSV file.

Usage:
  python3 run_api_from_csv.py \\
    --token-url https://nucleus.oaknorth.co.uk/identity/v1/token \\
    --tenant playground \\
    --refresh-token-env REFRESH_TOKEN \\
    --url https://host/api/loans/{loanId}/charges --method GET --csv data.csv

Set the refresh-token cookie value in an env var first, don't pass secrets on the CLI:
  export REFRESH_TOKEN='Bearer eyJhbGciOiJIUzUx...'

CSV columns become JSON body fields (POST/PUT/PATCH) or query params (GET/DELETE).
Use {col} placeholders in --url to substitute a column into the path instead.

Alternatively, pass --request-file pointing at a JSON file shaped
{"method", "url", "headers": [{"key","value"}], "body"}; url/body support
{{col}} placeholders (double braces) filled per row. --request-file takes
precedence over --method/--url when both are given.

On a 403, if --token-url is set the script regenerates the bearer token and
retries that row once. Rows that still fail after that (or that time out) are
written to --retry-csv instead of being counted as a hard failure:
  python3 run_api_from_csv.py ... --csv failed_rows.csv
"""
import argparse
import csv
import json
import os
import re
import string
import sys
import time

import requests

import assertions

DOUBLE_BRACE_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", help="Main API URL; supports {column} placeholders from the CSV. "
                                  "Required unless --request-file is given.")
    p.add_argument("--method", default="GET", help="HTTP method for the main API (default: GET)")
    p.add_argument("--request-file",
                    help="JSON file with {method,url,headers,body}; url/body support {{column}} placeholders. "
                         "Takes precedence over --method/--url when both are given.")
    p.add_argument("--csv", required=True, help="Path to CSV file; one API call per row")
    p.add_argument("-H", "--header", action="append", default=[], help="Extra header 'Key: Value' (repeatable)")
    p.add_argument("--delay", type=float, default=0, help="Seconds to sleep between calls (default: 0)")
    p.add_argument("--timeout", type=float, default=30, help="Per-request timeout in seconds (default: 30)")
    p.add_argument("--insecure", action="store_true", help="Skip TLS certificate verification")
    p.add_argument("--retry-csv", default="failed_rows.csv", help="Where to write flagged rows (default: failed_rows.csv)")

    p.add_argument("--token-url", help="Identity token endpoint; if set, a bearer token is generated and injected")
    p.add_argument("--tenant", help="x-tenant-identifier header value for the token request")
    p.add_argument("--refresh-token", help="Raw refreshToken cookie value, e.g. 'Bearer eyJ...'")
    p.add_argument("--refresh-token-env", help="Env var name holding the refreshToken cookie value")
    p.add_argument("--refresh-token-cookie-name", default="org.apache.fincn.refreshToken",
                    help="Cookie name for the refresh token (default: org.apache.fincn.refreshToken)")
    p.add_argument("--token-field", default="accessToken",
                    help="Field name in the token response JSON holding the access token (default: accessToken)")
    p.add_argument("--refresh-token-each-row", action="store_true",
                    help="Generate a fresh bearer token before every CSV row request")
    p.add_argument("--user", help="Value for a 'User' header on the main API call, e.g. pankaj.pandey")
    return p.parse_args()


def build_headers(raw_headers):
    headers = {}
    for h in raw_headers:
        key, _, value = h.partition(":")
        headers[key.strip()] = value.strip()
    return headers


def generate_token(args):
    refresh_token = args.refresh_token or os.environ.get(args.refresh_token_env or "", "")
    if not refresh_token:
        sys.exit("No refresh token supplied. Use --refresh-token or --refresh-token-env.")
    refresh_token = normalize_refresh_token(refresh_token, args.refresh_token_cookie_name)

    headers = {
        "Content-Type": "application/json",
        "x-tenant-identifier": args.tenant or "",
        "Cookie": f"{args.refresh_token_cookie_name}={refresh_token}",
    }
    body = {"grant_type": "refresh_token", "username": None, "password": None, "refreshTokenParam": None}
    resp = requests.post(args.token_url, headers=headers, json=body, verify=not args.insecure, timeout=args.timeout)
    if not resp.ok:
        sys.exit(f"Token request failed: {resp.status_code} {resp.text[:500]}")
    body = resp.json()
    token = body.get(args.token_field)
    if not token:
        redacted = {k: ("<redacted>" if "token" in k.lower() else v) for k, v in body.items()}
        sys.exit(f"Could not find field '{args.token_field}' in token response: {redacted}")
    return token


def normalize_refresh_token(value, cookie_name):
    value = (value or "").strip()
    prefix = f"{cookie_name}="
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    for part in value.split(";"):
        part = part.strip()
        if part.startswith(prefix):
            return part[len(prefix):].strip()
    return value


def refresh_auth_header(args, headers):
    token = generate_token(args)
    headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"


def url_placeholders(template):
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def substitute_double_brace(text, row):
    """Replace {{column}} with row[column]; leaves unknown placeholders untouched."""
    def repl(match):
        key = match.group(1)
        return str(row[key]) if key in row else match.group(0)
    return DOUBLE_BRACE_RE.sub(repl, text or "")


def load_request_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "method": data.get("method", "GET"),
        "url": data["url"],
        "headers": data.get("headers", []),
        "body": data.get("body") or "",
        "tests": data.get("tests") or [],
    }


def call_main_api_with_body(method, url, headers, timeout, insecure, body):
    """Request-file/console mode: `body` is the fully {{col}}-resolved string for
    this row (may legitimately be ""). Never derives params/body from the CSV row
    — doing so previously leaked every CSV column as a query param (GET/DELETE) or
    JSON body (POST/PUT) whenever the console request had an empty body."""
    kwargs = {"headers": headers, "verify": not insecure, "timeout": timeout}
    if body:
        kwargs["data"] = body.encode("utf-8")
    return requests.request(method, url, **kwargs)


def call_main_api_from_row(method, url_template, url, headers, row, timeout, insecure):
    """Legacy CLI mode: CSV columns not consumed by a {col} placeholder in the URL
    become JSON body fields (POST/PUT/PATCH) or query params (GET/DELETE)."""
    kwargs = {"headers": headers, "verify": not insecure, "timeout": timeout}
    remaining = {k: v for k, v in row.items() if k not in url_placeholders(url_template)}
    if method in ("GET", "DELETE"):
        if remaining:
            kwargs["params"] = remaining
    elif remaining:
        kwargs["json"] = remaining
    return requests.request(method, url, **kwargs)


def main():
    args = parse_args()
    if not args.request_file and not args.url:
        sys.exit("Either --url or --request-file is required.")

    headers = build_headers(args.header)

    request_template = None
    if args.request_file:
        request_template = load_request_file(args.request_file)
        for h in request_template["headers"]:
            headers[h["key"]] = h["value"]

    method = (request_template["method"] if request_template else args.method).upper()
    url_template = request_template["url"] if request_template else args.url
    body_template = request_template["body"] if request_template else None

    if method not in ("GET", "DELETE"):
        headers.setdefault("Content-Type", "application/json")

    if args.tenant:
        headers["x-tenant-identifier"] = args.tenant
    if args.user:
        headers["User"] = args.user
    if args.token_url and not args.refresh_token_each_row:
        refresh_auth_header(args, headers)

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        reader.fieldnames = fieldnames
        rows = list(reader)

    if not rows:
        print("CSV has no data rows.", file=sys.stderr)
        sys.exit(1)
    missing_placeholders = sorted(url_placeholders(url_template) - set(fieldnames)) if not request_template else []
    if missing_placeholders:
        print(
            "URL placeholder(s) not found in CSV header: "
            + ", ".join(missing_placeholders),
            file=sys.stderr,
        )
        print("Available CSV columns: " + (", ".join(fieldnames) if fieldnames else "(none)"), file=sys.stderr)
        sys.exit(1)

    row_tests = request_template.get("tests") if request_template else []
    ok, failed, flagged, retry_rows = 0, 0, 0, []
    tests_passed_total, tests_run_total = 0, 0
    for i, row in enumerate(rows, start=1):
        try:
            if request_template:
                url = substitute_double_brace(url_template, row)
                body = substitute_double_brace(body_template, row) if body_template else ""

                def _do_request(url=url, body=body):
                    return call_main_api_with_body(method, url, headers, args.timeout, args.insecure, body)
            else:
                url = args.url.format(**row)

                def _do_request(url=url):
                    return call_main_api_from_row(method, url_template, url, headers, row, args.timeout, args.insecure)

            if args.token_url and args.refresh_token_each_row:
                print(f"[{i}/{len(rows)}] TOKEN refreshing before {method} {url}", flush=True)
                refresh_auth_header(args, headers)
            print(f"[{i}/{len(rows)}] HIT {method} {url}", flush=True)
            resp = _do_request()
            if resp.status_code == 403 and args.token_url:
                print(f"[{i}/{len(rows)}] 403 -> refreshing token and retrying {method} {url}", flush=True)
                refresh_auth_header(args, headers)
                resp = _do_request()

            if resp.status_code == 403:
                flagged += 1
                retry_rows.append(row)
                print(f"[{i}/{len(rows)}] FLAGGED 403 (token expiry?) {url}", flush=True)
            elif row_tests:
                # Evaluate on every status code, not just 2xx — a test can legitimately
                # assert on a non-2xx response (e.g. status equals 404), and a malformed
                # test entry must fail this one row, not crash the whole batch.
                try:
                    results, _ = assertions.run_assertions(
                        row_tests,
                        {"status": resp.status_code, "headers": dict(resp.headers), "body": resp.text},
                        row,
                    )
                except Exception as exc:
                    failed += 1
                    retry_rows.append(row)
                    print(f"[{i}/{len(rows)}] ERROR evaluating tests -> {exc}", flush=True)
                else:
                    passed_count = sum(1 for r in results if r.get("passed"))
                    total_count = len(results)
                    tests_passed_total += passed_count
                    tests_run_total += total_count
                    if passed_count < total_count:
                        failed += 1
                        retry_rows.append(row)
                        print(f"[{i}/{len(rows)}] FAIL tests {passed_count}/{total_count} {resp.status_code} {url} -> {resp.text[:200]}", flush=True)
                    else:
                        ok += 1
                        print(f"[{i}/{len(rows)}] OK {resp.status_code} tests {passed_count}/{total_count} {url} -> {resp.text[:200]}", flush=True)
            elif resp.ok:
                ok += 1
                print(f"[{i}/{len(rows)}] OK {resp.status_code} {url} -> {resp.text[:200]}", flush=True)
            else:
                failed += 1
                retry_rows.append(row)
                print(f"[{i}/{len(rows)}] FAIL {resp.status_code} {url} -> {resp.text[:200]}", flush=True)
        except requests.Timeout:
            flagged += 1
            retry_rows.append(row)
            print(f"[{i}/{len(rows)}] FLAGGED timeout {url}", flush=True)
        except requests.RequestException as e:
            failed += 1
            retry_rows.append(row)
            print(f"[{i}/{len(rows)}] ERROR {url} -> {e}", flush=True)
        except KeyError as e:
            failed += 1
            retry_rows.append(row)
            print(f"[{i}/{len(rows)}] ERROR row missing column {e} for template -> {row}", flush=True)

        if args.delay:
            time.sleep(args.delay)

    if retry_rows:
        with open(args.retry_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(retry_rows)
        print(f"\nFailed/flagged {len(retry_rows)} row(s) written to {args.retry_csv} for re-run.", flush=True)

    tests_note = f", tests {tests_passed_total}/{tests_run_total}" if row_tests else ""
    print(f"Done: {ok} succeeded, {failed} failed, {flagged} flagged, out of {len(rows)}{tests_note}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
