import ipaddress
import secrets

from fastapi import Header, HTTPException, Request

from ..config import settings

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def is_local(host: str) -> bool:
    """A request from this machine: loopback, or an address in RAG_ADMIN_HOSTS (IPs or CIDRs).
    Behind Docker port publishing the browser on the host arrives from the bridge gateway (e.g. 172.18.0.1),
    so the compose file binds the port to 127.0.0.1 and lists the bridge range here."""
    if host in LOOPBACK:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for item in filter(None, (s.strip() for s in settings.admin_hosts.split(","))):
        try:
            if addr in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def _bearer_ok(authorization: str | None) -> bool:
    scheme, _, token = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token.strip(), settings.api_key)


def require_key(authorization: str | None = Header(None)) -> None:
    """Ingest API: open when RAG_API_KEY is empty, otherwise needs the Bearer key."""
    if settings.api_key and not _bearer_ok(authorization):
        raise HTTPException(401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})


def require_admin(request: Request, authorization: str | None = Header(None)) -> None:
    """Server settings: needs the Bearer key when RAG_API_KEY is set, otherwise a request from this machine."""
    if settings.api_key:
        if not _bearer_ok(authorization):
            raise HTTPException(401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})
    elif not is_local(request.client.host if request.client else ""):
        raise HTTPException(403, "set RAG_API_KEY to change settings from another machine")
