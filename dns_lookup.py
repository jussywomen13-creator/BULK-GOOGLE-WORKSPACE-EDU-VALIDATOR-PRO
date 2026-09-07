"""DNS/MX lookup helpers.

DNS/MX checks only indicate whether a domain is technically reachable for
email. They never verify that a specific mailbox exists.
"""

import time

import dns.exception
import dns.resolver

from config import Config


def lookup_domain(domain: str, timeout: int | None = None, retries: int = 1) -> dict:
    timeout = timeout if timeout is not None else Config.DNS_TIMEOUT
    records = {
        "mx": [],
        "a": [],
        "aaaa": [],
        "has_mx": False,
        "has_a": False,
        "null_mx": False,
        "error": None,
    }
    if not domain:
        records["error"] = "Missing domain"
        return records

    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = float(timeout)
    resolver.timeout = float(timeout)

    attempts = 0
    last_error = None
    while attempts < max(1, retries + 1):
        attempts += 1
        last_error = None

        # MX
        try:
            answers = resolver.resolve(domain, "MX", lifetime=float(timeout))
            mx = sorted(
                [(r.preference, str(r.exchange).rstrip(".")) for r in answers],
                key=lambda x: (x[0], x[1]),
            )
            real_mx = [exchange for pref, exchange in mx if exchange]
            records["mx"] = real_mx
            records["has_mx"] = bool(real_mx)
            # RFC 7505 Null MX indicates that the domain does not accept email.
            if not real_mx and mx:
                records["null_mx"] = True
        except dns.resolver.NXDOMAIN:
            last_error = "NXDOMAIN (domain does not exist)"
        except dns.resolver.NoAnswer:
            last_error = "NoAnswer (no MX records)"
        except (dns.resolver.LifetimeTimeout, dns.resolver.Timeout, dns.exception.DNSException) as exc:
            last_error = f"{type(exc).__name__}: DNS lookup failed or timed out"

        if not last_error or last_error.startswith("NoAnswer"):
            break

        if attempts < max(1, retries + 1):
            time.sleep(0.05)

    if records["has_mx"]:
        # Some domains have MX but no A; that is a valid mail domain.
        # No exception was raised, so clear last_error.
        last_error = None

    if last_error and isinstance(last_error, str) and last_error.startswith("NXDOMAIN"):
        records["error"] = last_error
        return records

    # A/AAAA (glue/fallback info, does not prove mailbox existence)
    if not records["has_mx"]:
        for qtype, key in [("A", "a"), ("AAAA", "aaaa")]:
            try:
                answers = resolver.resolve(domain, qtype, lifetime=float(timeout))
                records[key] = [r.to_text() for r in answers][:20]
            except dns.resolver.NoAnswer:
                pass
            except (dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout, dns.resolver.Timeout, dns.exception.DNSException):
                pass
        records["has_a"] = bool(records["a"] or records["aaaa"])
        if not records["has_a"] and not records["has_mx"]:
            records["error"] = last_error or "Domain did not resolve A/MX"

    return records


def mx_records_to_text(mx: list) -> str:
    import json

    return json.dumps(mx, ensure_ascii=False)
