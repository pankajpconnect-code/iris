import run_auth


def test_token_cache_mints_oauth2_client_credentials_on_first_get(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"minted-abc"}'}])
    auth_cfg = {
        "mode": "oauth2-client-credentials",
        "oauth2ClientId": "cid",
        "oauth2ClientSecret": "csecret",
        "oauth2TokenUrl": fake_server.url("/token"),
        "oauth2AuthStyle": "basic-header",
    }
    cache = run_auth.TokenCache(auth_cfg)

    token, epoch = cache.get()

    assert token == "minted-abc"
    assert epoch == 0


def test_token_cache_auth_for_send_reports_oauth2_as_bearer(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"minted-xyz"}'}])
    auth_cfg = {
        "mode": "oauth2-client-credentials",
        "oauth2ClientId": "cid",
        "oauth2ClientSecret": "csecret",
        "oauth2TokenUrl": fake_server.url("/token"),
        "oauth2AuthStyle": "post-body",
    }
    cache = run_auth.TokenCache(auth_cfg)

    sent = cache.auth_for_send()

    assert sent == {"mode": "bearer", "bearerToken": "minted-xyz"}


def test_token_cache_requires_minting_true_for_oauth2_with_token_url():
    cache = run_auth.TokenCache({"mode": "oauth2-client-credentials", "oauth2TokenUrl": "https://x/token"})
    assert cache.requires_minting() is True


def test_token_cache_requires_minting_false_for_oauth2_without_token_url():
    cache = run_auth.TokenCache({"mode": "oauth2-client-credentials"})
    assert cache.requires_minting() is False


def test_token_cache_mint_failure_raises_token_mint_failed(fake_server):
    fake_server.set_responses("/token", [{"status": 401, "body": '{"error":"invalid_client"}'}])
    auth_cfg = {
        "mode": "oauth2-client-credentials",
        "oauth2ClientId": "cid",
        "oauth2ClientSecret": "bad",
        "oauth2TokenUrl": fake_server.url("/token"),
    }
    cache = run_auth.TokenCache(auth_cfg)

    try:
        cache.get()
        assert False, "expected TokenMintFailed"
    except run_auth.TokenMintFailed:
        pass
