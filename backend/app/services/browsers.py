"""A short name for a browser, from its User-Agent header: "Firefox on Windows" (ACCT-006,
ACCT-007). For people to recognise their own sessions, so only the browser's family and
the system it runs on, never its version or the header itself. A header can say anything;
the name is only ever shown, never trusted."""

# Checked in order: Edge's and Opera's headers also say Chrome and Safari, Chrome's says Safari.
_BROWSERS = (
    ("Edg", "Edge"),
    ("OPR/", "Opera"),
    ("Opera", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Chromium/", "Chromium"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("CrOS", "ChromeOS"),
    ("Windows", "Windows"),
    ("Macintosh", "macOS"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)
UNKNOWN = "Unknown browser"


def browser_name(user_agent: str | None) -> str:
    if not user_agent:
        return UNKNOWN
    browser = next((name for marker, name in _BROWSERS if marker in user_agent), None)
    system = next((name for marker, name in _SYSTEMS if marker in user_agent), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or (f"A browser on {system}" if system else UNKNOWN)
