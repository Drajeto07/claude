import traceback


def where(exc: BaseException, frames: int = 3) -> str:
    """Where `exc` was raised: the innermost frames' file and line, innermost first --
    never its message, which can quote the file being read (SEC-010, SEC-011)."""
    innermost = traceback.extract_tb(exc.__traceback__)[-frames:] if exc.__traceback__ else []
    return " < ".join(f"{frame.filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame.lineno}" for frame in reversed(innermost)) or "?"
