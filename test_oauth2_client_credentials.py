import pytest

import oauth2_client_credentials


def test_mint_client_credentials_token_basic_header_style(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"abc123"}'}])

    token = oauth2_client_credentials.mint_client_credentials_token(
        client_id="cid", client_secret="csecret", token_url=fake_server.url("/token"),
        scope=None, auth_style="basic-header", timeout=5,
    )

    assert token == "abc123"
    sent = fake_server.requests[0]
    assert sent["headers"]["Authorization"].startswith("Basic ")
    assert "client_id" not in sent["body"]
    assert "client_secret" not in sent["body"]


def test_mint_client_credentials_token_post_body_style(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"xyz789"}'}])

    token = oauth2_client_credentials.mint_client_credentials_token(
        client_id="cid", client_secret="csecret", token_url=fake_server.url("/token"),
        scope="read write", auth_style="post-body", timeout=5,
    )

    assert token == "xyz789"
    sent = fake_server.requests[0]
    assert "Authorization" not in sent["headers"]
    assert "client_id=cid" in sent["body"]
    assert "client_secret=csecret" in sent["body"]
    assert "scope=read" in sent["body"]


def test_mint_client_credentials_token_non_2xx_response_exits(fake_server):
    fake_server.set_responses("/token", [{"status": 401, "body": '{"error":"invalid_client"}'}])

    with pytest.raises(SystemExit):
        oauth2_client_credentials.mint_client_credentials_token(
            client_id="cid", client_secret="bad", token_url=fake_server.url("/token"),
            scope=None, auth_style="basic-header", timeout=5,
        )


def test_mint_client_credentials_token_missing_access_token_exits(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"token_type":"bearer"}'}])

    with pytest.raises(SystemExit):
        oauth2_client_credentials.mint_client_credentials_token(
            client_id="cid", client_secret="csecret", token_url=fake_server.url("/token"),
            scope=None, auth_style="basic-header", timeout=5,
        )
