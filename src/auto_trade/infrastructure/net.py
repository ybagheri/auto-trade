from __future__ import annotations

import hmac
from http.client import HTTPMessage
from typing import IO
from urllib.error import URLError
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, Request

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
MAX_RESPONSE_BYTES = 64 * 1024


class NonLoopbackRedirectError(URLError):
    """Raised when a redirect would move an authenticated request off loopback."""


class LoopbackOnlyRedirectHandler(HTTPRedirectHandler):
    """Refuses a redirect that would move a request off loopback.

    The standard library follows a redirect with the original headers intact, so
    an unguarded client resends its bearer token to a host the operator never
    configured. Both the signal provider and the local API client fail closed
    instead, which is why this policy lives in one place: the two must not be
    able to disagree about it.
    """

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        host = urlsplit(newurl).hostname or ""
        if not is_loopback(host):
            raise NonLoopbackRedirectError(
                f"refusing to follow a redirect to non-loopback host {host!r}; it would "
                "resend the configured token to a host that was never configured"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def constant_time_equals(supplied: str, expected: str) -> bool:
    """Compare two secrets without an early exit on the first differing byte."""
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


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
