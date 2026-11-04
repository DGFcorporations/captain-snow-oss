import secrets


def chat_auth_failure_status(expected_token: str, authorization: str) -> int | None:
    """Return an HTTP failure status, or None for an authorized request.

    An unset server token is a configuration failure, never an open-access mode.
    """
    if not expected_token:
        return 503
    parts = authorization.split(None, 1)
    supplied = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""
    return None if secrets.compare_digest(supplied, expected_token) else 401
