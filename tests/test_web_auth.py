from ui.auth import chat_auth_failure_status


def test_missing_server_token_fails_closed():
    assert chat_auth_failure_status("", "") == 503
    assert chat_auth_failure_status("", "Bearer any-client-value") == 503


def test_only_matching_bearer_token_is_accepted():
    assert chat_auth_failure_status("server-token", "Bearer server-token") is None
    assert chat_auth_failure_status("server-token", "Bearer wrong") == 401
    assert chat_auth_failure_status("server-token", "server-token") == 401
    assert chat_auth_failure_status("server-token", "Basic server-token") == 401
