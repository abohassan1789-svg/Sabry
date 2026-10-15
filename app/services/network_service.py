"""Network validation for the CRM server connection.

Pure standard library so it works both inside the installer's bundled Python and
in the running app. Every check returns a small result object with a clear
message the UI (installer wizard or Settings screen) can show directly.

Provided checks:

* :func:`detect_ipv4_addresses`  — local IPv4 addresses for the LAN dropdown.
* :func:`is_port_available`       — can we *bind* this port here (server side)?
* :func:`can_reach`               — can we open a TCP connection to host:port?
* :func:`test_database`           — can we actually authenticate to PostgreSQL?
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    ok: bool
    message: str
    detail: str = ""

    def __bool__(self) -> bool:  # allow `if result:`
        return self.ok


# ---------------------------------------------------------------------------
# IP detection
# ---------------------------------------------------------------------------


def detect_ipv4_addresses() -> list[str]:
    """Return this machine's usable IPv4 addresses, best candidate first.

    Ordering: the address used to reach the default gateway (the most likely LAN
    address) first, then other private addresses, then the rest. Loopback and
    link-local (169.254.x) are excluded.
    """
    found: list[str] = []

    # 1) Primary outbound address (no traffic is actually sent by connect()).
    primary = _primary_outbound_ip()
    if primary:
        found.append(primary)

    # 2) Everything the resolver knows about this host.
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, family=socket.AF_INET):
            addr = info[4][0]
            if addr not in found:
                found.append(addr)
    except socket.gaierror:
        pass

    def usable(a: str) -> bool:
        try:
            ip = ipaddress.IPv4Address(a)
        except ipaddress.AddressValueError:
            return False
        return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified)

    def rank(a: str) -> tuple[int, str]:
        # Private LAN addresses rank ahead of public ones.
        try:
            return (0 if ipaddress.IPv4Address(a).is_private else 1, a)
        except ipaddress.AddressValueError:
            return (2, a)

    unique = [a for a in dict.fromkeys(found) if usable(a)]
    # Keep the detected primary first, sort the remainder by privateness.
    if unique:
        head, *tail = unique
        tail.sort(key=rank)
        return [head, *tail]
    return unique


def _primary_outbound_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not send packets; just picks the route/source address.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Port checks
# ---------------------------------------------------------------------------


def is_port_available(port: int, address: str = "0.0.0.0") -> CheckResult:
    """Can the server bind *port* on *address* right now?

    Used before finishing installation to confirm the chosen PostgreSQL port is
    free (or, if PostgreSQL is already listening on it, that is reported clearly
    rather than as a hard failure).
    """
    if not (1 <= int(port) <= 65535):
        return CheckResult(False, f"Port {port} is out of range (1–65535).")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind((address, int(port)))
        s.listen(1)
        return CheckResult(True, f"Port {port} is available and can be bound.")
    except OSError as exc:
        # Something already listens here. If it's our own PostgreSQL, that's fine.
        already = can_reach(_bind_probe_host(address), port, timeout=0.5)
        if already.ok:
            return CheckResult(
                True,
                f"Port {port} is already in use by a listening service "
                f"(likely PostgreSQL). This is expected on reinstall.",
                detail=str(exc),
            )
        return CheckResult(False, f"Cannot bind port {port}: {exc}", detail=str(exc))
    finally:
        s.close()


def _bind_probe_host(address: str) -> str:
    return "127.0.0.1" if address in ("0.0.0.0", "", "::") else address


def can_reach(host: str, port: int, timeout: float = 3.0) -> CheckResult:
    """Can we open a TCP connection to host:port?"""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return CheckResult(True, f"Reached {host}:{port}.")
    except OSError as exc:
        return CheckResult(False, f"Could not reach {host}:{port}: {exc}", detail=str(exc))


# ---------------------------------------------------------------------------
# Database check
# ---------------------------------------------------------------------------


def test_database(
    host: str,
    port: int,
    db_name: str,
    user: str,
    password: str,
    sslmode: str = "prefer",
    timeout: float = 5.0,
) -> CheckResult:
    """Attempt a real PostgreSQL connection (SELECT 1).

    Falls back to a plain TCP reachability check if the ``psycopg`` driver is not
    importable, so the caller still gets a useful signal.
    """
    try:
        import psycopg
    except ImportError:
        reach = can_reach(host, port, timeout=timeout)
        if reach.ok:
            return CheckResult(
                True,
                f"TCP port {host}:{port} is open (psycopg not installed, so "
                "credentials were not verified).",
            )
        return reach

    # Keyword arguments, not a "key=value" string: psycopg quotes each value, so
    # a password with spaces, quotes or backslashes is passed unchanged and is
    # never echoed back in a parse error.
    params = dict(host=host, port=int(port), dbname=db_name, user=user,
                  password=password, sslmode=sslmode, connect_timeout=int(timeout))
    try:
        with psycopg.connect(**params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return CheckResult(True, f"Connected to database '{db_name}' on {host}:{port}.")
    except Exception as exc:  # psycopg.OperationalError and friends
        return CheckResult(False, f"Database connection failed: {exc}", detail=str(exc))


def _is_missing_database(text: str) -> bool:
    lowered = (text or "").lower()
    return "database" in lowered and "does not exist" in lowered


def test_database_or_server(
    host: str,
    port: int,
    db_name: str,
    user: str,
    password: str,
    sslmode: str = "prefer",
    maintenance_db: str = "postgres",
) -> tuple[CheckResult, bool]:
    """Test ``db_name``; if only the database is missing, test the server instead.

    Returns ``(result, db_missing)``. Used on the main machine, where the
    installer creates the database after the test, so a reachable server with
    valid credentials is a pass.
    """
    result = test_database(host, port, db_name, user, password, sslmode=sslmode)
    if result.ok or not _is_missing_database(result.detail or result.message):
        return result, False
    server = test_database(host, port, maintenance_db, user, password, sslmode=sslmode)
    if server.ok:
        return CheckResult(
            True,
            f"Server {host}:{port} reachable; database '{db_name}' will be created.",
        ), True
    return server, True


def friendly_db_message(host: str, port: int, db_name: str, user: str, detail: str) -> str:
    """One short sentence for the installer instead of psycopg's multi-line error."""
    text = (detail or "").lower()
    if "password authentication failed" in text:
        return f'Wrong password for user "{user}".'
    if "does not exist" in text and "database" in text:
        return (f'Database "{db_name}" does not exist on {host}. Install the MAIN machine '
                "first, or check the Host / IP address.")
    if "role" in text and "does not exist" in text:
        return f'User "{user}" does not exist on the PostgreSQL server.'
    if any(k in text for k in ("connection refused", "timeout", "timed out",
                               "could not connect", "no route", "could not translate")):
        return (f"Cannot reach PostgreSQL at {host}:{port}. Check that the PostgreSQL "
                "service is running, the Host / IP address is correct, and the firewall "
                "allows port " + str(port) + ".")
    first = (detail or "").strip().splitlines()
    return first[0] if first else "Connection failed."

