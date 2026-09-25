def error_body(response) -> dict:
    """An error response's body without its request id, which every request has
    its own of -- for checking two errors say exactly the same thing."""
    return {key: value for key, value in response.json().items() if key != "request_id"}
