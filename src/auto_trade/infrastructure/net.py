from __future__ import annotations

from urllib.parse import SplitResult, urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
MAX_RESPONSE_BYTES = 64 * 1024


def is_loopback(host: str) -> bool:
    """Report whether *host* names this machine and nothing else.

    Comparison is done on the literal host string, so a name that merely looks
    like loopback, such as ``localhost.example.com`` or ``127.0.0.1.nip.io``,
    is not accepted.
    """
    return host.strip().lower().strip("[]") in LOOPBACK_HOSTS


def split_loopback_url(url: str, purpose: str) -> SplitResult:
    """Split *url* and refuse anything that is not an explicit loopback URL.

    A signal or control surface that answers on a routable address would expose
    this bridge to the network, so the caller is expected to fail closed rather
    than to downgrade to a weaker check.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"{purpose} must use http or https, got {parts.scheme!r}")
    host = parts.hostname or ""
    if not is_loopback(host):
        raise ValueError(
            f"refusing {purpose} at {host or url!r}: it must stay on loopback "
            f"({', '.join(sorted(LOOPBACK_HOSTS))})"
        )
    return parts


def safe_url_summary(url: str) -> str:
    """Return a loggable form of *url* with credentials, query, and fragment removed.

    Diagnostics and audit records must never echo a token, and a token pasted
    into the query string is a token this application will not send.
    """
    if not url.strip():
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme and not parts.netloc:
        return ""
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{host}{port}{path}"
