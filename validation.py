"""Email syntax, domain, and risk-signal validation.

This module performs only legitimate email-list hygiene checks. It never checks
passwords, cookies, session tokens, login credentials, or attempts mailbox
login/enumeration.
"""

import ipaddress
import re

MAX_EMAIL_LENGTH = 254
MAX_LOCAL_LENGTH = 64

EMAIL_SYNTAX_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

EXTRACT_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+"
)

# Statuses exposed by the application.
PENDING = "PENDING"
DELIVERABILITY_LIKELY = "DELIVERABILITY_LIKELY"
INVALID = "INVALID"
RISKY = "RISKY"
CATCH_ALL = "CATCH_ALL"
DISPOSABLE = "DISPOSABLE"
ROLE = "ROLE"
DUPLICATE = "DUPLICATE"
UNKNOWN = "UNKNOWN"
ERROR = "ERROR"

VALID_STATUSES = {
    DELIVERABILITY_LIKELY,
    INVALID,
    RISKY,
    CATCH_ALL,
    DISPOSABLE,
    ROLE,
    DUPLICATE,
    UNKNOWN,
    ERROR,
    PENDING,
}

ROLE_PREFIXES = {
    "abuse",
    "account",
    "accounts",
    "admin",
    "administration",
    "billing",
    "contact",
    "customerservice",
    "dev",
    "developer",
    "development",
    "finance",
    "help",
    "helpdesk",
    "hr",
    "info",
    "information",
    "investor",
    "investors",
    "it",
    "jobs",
    "legal",
    "management",
    "marketing",
    "no-reply",
    "no-reply",
    "noreply",
    "office",
    "ops",
    "operations",
    "postmaster",
    "press",
    "privacy",
    "product",
    "purchasing",
    "recruiting",
    "sales",
    "security",
    "service",
    "services",
    "support",
    "system",
    "team",
    "test",
    "unsubscribe",
    "webmaster",
}

FREE_PROVIDERS = {
    "aol.com",
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "hotmail.co.uk",
    "outlook.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.co.uk",
    "yahoo.fr",
    "ymail.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "proton.me",
    "protonmail.com",
    "zoho.com",
    "gmx.com",
    "gmx.net",
    "mail.com",
    "mail.ru",
    "yandex.com",
    "yandex.ru",
    "qq.com",
    "163.com",
    "126.com",
    "sina.com",
    "facebook.com",
    "free.fr",
}

DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "10minutemail.net",
    "20minutemail.com",
    "33mail.com",
    "999mailbox.com",
    "abcmail.email",
    "accountant.com",
    "ag.us.to",
    "allmail.net",
    "anonymousemail.me",
    "anonymbox.com",
    "antichef.com",
    "binkmail.com",
    "bobmail.info",
    "boximail.com",
    "bugmenot.com",
    "burnmail.com",
    "casualtycertificate.com",
    "chammy.info",
    "cheatmail.de",
    "cryptonut.net",
    "cuirushi.org",
    "cyber-innovation.com",
    "dispostable.com",
    "dodsi.com",
    "dropmail.me",
    "emailfake.com",
    "emailias.com",
    "emailondeck.com",
    "emlpro.com",
    "fakeinbox.com",
    "fake-mail.net",
    "filzmail.com",
    "getnada.com",
    "getairmail.com",
    "guerrillamail.com",
    "guerrillamail.net",
    "guerrillamail.org",
    "guerrillamailblock.com",
    "gustr.com",
    "hai5.net",
    "harakirimail.com",
    "hi2.in",
    "hidester.com",
    "hmamail.com",
    "hotpop.com",
    "inboxbear.com",
    "incognitomail.com",
    "jetable.com",
    "jetable.org",
    "junkmail.com",
    "kuku.ml",
    "linkbits.com",
    "loremipsum.info",
    "mailcatch.com",
    "maildrop.cc",
    "mailinator.com",
    "mailinator.net",
    "mailnesia.com",
    "mailshell.com",
    "meltmail.com",
    "mintemail.com",
    "moakt.com",
    "moakt.co",
    "mt2009.com",
    "my10minutemail.com",
    "mytrashmail.com",
    "nada.email",
    "nat1.net",
    "negateable.com",
    "nihilismus.net",
    "no-spam.ws",
    "nospam.ze.tc",
    "nullbox.info",
    "nurfuerspam.de",
    "objectmail.com",
    "obfusko.com",
    "ocallahan.com",
    "oiwqd.com",
    "oxynet.org",
    "pancakemail.com",
    "pinktower.com",
    "pointcut.com",
    "privacy.net",
    "punkass.com",
    "quickinbox.com",
    "reciet.com",
    "rcpt.at",
    "recyclemail.dk",
    "rejectmail.com",
    "s0ny.net",
    "safe-mail.net",
    "sharklasers.com",
    "silkroad.net",
    "snakemail.com",
    "spam4.me",
    "spambox.us",
    "spamfree24.org",
    "spamgourmet.com",
    "spamspot.com",
    "squizzy.de",
    "ssoia.com",
    "startfu.com",
    "superrito.com",
    "surreymail.com",
    "talkinator.com",
    "teewars.org",
    "temp-mail.org",
    "tempail.com",
    "tempemail.net",
    "tempmail.plus",
    "tempmailaddress.com",
    "tempmailer.com",
    "tempm.com",
    "temporaryemail.net",
    "throwawayemail.com",
    "trashmail.com",
    "trashmail.net",
    "trashymail.com",
    "trbvm.com",
    "tugssl.com",
    "u153.com",
    "u145.com",
    "u163.com",
    "u170.com",
    "u173.com",
    "u174.com",
    "u176.com",
    "u177.com",
    "u178.com",
    "u179.com",
    "u180.com",
    "u181.com",
    "u182.com",
    "u183.com",
    "u184.com",
    "u185.com",
    "u186.com",
    "u187.com",
    "u188.com",
    "u189.com",
    "u190.com",
    "u200.com",
    "u202.com",
    "u203.com",
    "u204.com",
    "u205.com",
    "u206.com",
    "u207.com",
    "u208.com",
    "u209.com",
    "u210.com",
    "u211.com",
    "u212.com",
    "u213.com",
    "u214.com",
    "u215.com",
    "u216.com",
    "u217.com",
    "u218.com",
    "u219.com",
    "u220.com",
    "u221.com",
    "u222.com",
    "u223.com",
    "u224.com",
    "u225.com",
    "u226.com",
    "u227.com",
    "u228.com",
    "u229.com",
    "u230.com",
    "u231.com",
    "u232.com",
    "u233.com",
    "u234.com",
    "u235.com",
    "u236.com",
    "u237.com",
    "u238.com",
    "u239.com",
    "u240.com",
    "u241.com",
    "u242.com",
    "u243.com",
    "u244.com",
    "u245.com",
    "u246.com",
    "u247.com",
    "u248.com",
    "u249.com",
    "u250.com",
    "u251.com",
    "u252.com",
    "u253.com",
    "u254.com",
    "u255.com",
    "u256.com",
    "u257.com",
    "u258.com",
    "u259.com",
    "u260.com",
    "u261.com",
    "u262.com",
    "u263.com",
    "u264.com",
    "u265.com",
    "u266.com",
    "u267.com",
    "u268.com",
    "u269.com",
    "u270.com",
    "u271.com",
    "u272.com",
    "u273.com",
    "u274.com",
    "u275.com",
    "u276.com",
    "u277.com",
    "u278.com",
    "u279.com",
    "u280.com",
    "waiting-mind.com",
    "wetinbox.com",
    "winemaven.info",
    "wronghead.com",
    "yopmail.com",
    "yopmail.fr",
    "yopmail.net",
    "zehnminutenmail.de",
    "zoomail.com",
    "0-180.com",
    "0xffff.eu",
    "1taps.com",
    "5ghost.net",
}

# Known conservative catch-all patterns. Only considered when the optional
# catch-all probe is explicitly enabled. We never detect catch-all from MX alone.
DEFAULT_CATCH_ALL_PATTERNS = [
    "catchall.ru",
    "mailexpire.com",
]


def normalize_email(raw: str) -> str:
    """Normalize an email to lower-case and strip surrounding whitespace."""
    if raw is None:
        return ""
    value = raw.strip().lower()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    # Trim trailing punctuation that often comes from prose.
    value = value.strip(".,;:()[]{}<>\"'")
    return value


def extract_domain(email: str) -> str:
    """Extract and normalize the domain from an email address."""
    if not email:
        return ""
    parts = email.rsplit("@", 1)
    if len(parts) != 2:
        return ""
    domain = parts[1].strip().lower().rstrip(".")
    return domain


def is_valid_email_syntax(email: str) -> bool:
    if not email or len(email) > MAX_EMAIL_LENGTH:
        return False
    if "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    if not local or len(local) > MAX_LOCAL_LENGTH:
        return False
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    if not EMAIL_SYNTAX_RE.match(email):
        return False
    # Domain literals are not supported for list hygiene in this app.
    if domain.startswith("[") or domain.endswith("]"):
        return False
    try:
        ipaddress.ip_address(domain)
        return False
    except ValueError:
        pass
    return True


def is_valid_domain_format(domain: str) -> bool:
    """Validate domain syntax without DNS (format-only)."""
    if not domain or len(domain) > 253:
        return False
    if not domain or "." not in domain:
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label.startswith("-") or label.endswith("-"):
            return False
        if not re.match(r"^[a-z0-9-]+$", label):
            return False
    tld = labels[-1]
    if not re.match(r"^[a-z]{2,}$", tld):
        return False
    return True


def detect_disposable(domain: str) -> bool:
    return domain in DISPOSABLE_DOMAINS


def detect_role(email: str) -> bool:
    local = email.rsplit("@", 1)[0].lower()
    return local in ROLE_PREFIXES


def detect_free_provider(domain: str) -> bool:
    return domain in FREE_PROVIDERS


def is_confirmed_catch_all(domain: str) -> bool:
    return domain in DEFAULT_CATCH_ALL_PATTERNS


def risk_signals_from_email(email: str, domain: str) -> list:
    """Return a list of {type, label, detail} risk signals."""
    signals = []
    if detect_disposable(domain):
        signals.append(
            {
                "type": "disposable",
                "label": "Disposable provider",
                "detail": "Domain appears on a known disposable/temporary email list.",
            }
        )
    if detect_role(email):
        signals.append(
            {
                "type": "role",
                "label": "Role address",
                "detail": "Local part is a common shared/role mailbox prefix.",
            }
        )
    if detect_free_provider(domain):
        signals.append(
            {
                "type": "free_provider",
                "label": "Free provider",
                "detail": "Domain is a well-known free email provider.",
            }
        )
    if _catchall_enabled and is_confirmed_catch_all(domain):
        signals.append(
            {
                "type": "catch_all",
                "label": "Confirmed catch-all",
                "detail": "Domain is present on the verified catch-all risk list.",
            }
        )
    return signals


_catchall_enabled = False


def set_catchall_enabled(enabled: bool) -> None:
    global _catchall_enabled
    _catchall_enabled = bool(enabled)


def classify_email(email: str, dns_result: dict | None = None) -> dict:
    """Classify a single email using syntax, domain format and DNS.

    Returns dict with status, reason, domain, mx_records, risk_signals and a
    `dns` block describing exactly what was attempted.

    DNS/MX success only indicates deliverability *potential*. It never proves
    that a specific mailbox exists.
    """
    normalized = normalize_email(email)
    domain = extract_domain(normalized)

    if not normalized or "@" not in normalized:
        return _result(normalized, domain, INVALID, "Email syntax is invalid: missing @", None, [])

    if not is_valid_email_syntax(normalized):
        return _result(
            normalized,
            domain,
            INVALID,
            "Email syntax failed local/domain format validation.",
            None,
            [],
        )

    if not is_valid_domain_format(domain):
        return _result(
            normalized,
            domain,
            INVALID,
            "Domain format is invalid (bad labels, TLD, or length).",
            None,
            [],
        )

    if domain.lower().endswith(".invalid") or domain.lower().endswith(".local"):
        return _result(
            normalized,
            domain,
            INVALID,
            "Domain is a reserved/non-routable test TLD.",
            None,
            [],
        )

    signals = risk_signals_from_email(normalized, domain)

    if any(s["type"] == "disposable" for s in signals):
        return _result(
            normalized,
            domain,
            DISPOSABLE,
            "Disposable/temporary email provider detected.",
            None,
            signals,
        )

    if any(s["type"] == "catch_all" for s in signals):
        return _result(
            normalized,
            domain,
            CATCH_ALL,
            "Domain is from a verified catch-all risk list.",
            None,
            signals,
        )

    if any(s["type"] == "role" for s in signals):
        return _result(
            normalized,
            domain,
            ROLE,
            "Shared/role mailbox address detected.",
            None,
            signals,
        )

    if dns_result is None:
        return _result(
            normalized,
            domain,
            DELIVERABILITY_LIKELY,
            "Syntax and risk signals valid; DNS verification was not attempted in this call.",
            None,
            signals,
        )

    if dns_result.get("error"):
        return _result(
            normalized,
            domain,
            UNKNOWN,
            f"DNS/MX lookup failed or timed out: {dns_result['error']}",
            None,
            signals,
        )

    if dns_result.get("has_mx"):
        reasons = [
            "Syntax valid",
            "Domain format valid",
            f"{len(dns_result.get('mx', []))} MX record(s) resolved",
        ]
        if "a" in dns_result and dns_result.get("a"):
            reasons.append("A record resolved")
        if signals:
            reasons.append("Risk signals present; mailbox existence is NOT verified")
        return _result(
            normalized,
            domain,
            DELIVERABILITY_LIKELY,
            " ".join(reasons) + ". Deliverability potential only; DNS/MX does not prove a mailbox exists.",
            dns_result.get("mx", []),
            signals,
        )

    if dns_result.get("has_a"):
        return _result(
            normalized,
            domain,
            RISKY,
            "Domain resolves but has no MX records; RFC-aware mail delivery is unlikely.",
            dns_result.get("mx", []),
            signals,
        )

    return _result(
        normalized,
        domain,
        INVALID,
        "Domain does not resolve and has no A/MX records.",
        dns_result.get("mx", []),
        signals,
    )


def _result(email, domain, status, reason, mx, signals) -> dict:
    return {
        "email": email,
        "domain": domain,
        "status": status,
        "reason": reason,
        "mx_records": mx or [],
        "risk_signals": signals or [],
        "dns": {},
    }
