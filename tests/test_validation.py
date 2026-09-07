from extraction import (
    extract_emails_from_file,
    extract_emails_from_text,
    normalize_and_dedupe,
)
from validation import (
    DELIVERABILITY_LIKELY,
    INVALID,
    RISKY,
    classify_email,
    is_valid_domain_format,
    is_valid_email_syntax,
    normalize_email,
)


def test_normalize_email():
    assert normalize_email("  User.Name@Example.COM  ") == "user.name@example.com"
    assert normalize_email("<Admin@example.com>") == "admin@example.com"


def test_extract_emails_from_text():
    text = "Contact us at Alpha@Example.com or Sales@test.co (John <sales@test.co>)"
    emails = extract_emails_from_text(text)
    normalized = {emails[i]["raw_email"].lower() for i in range(len(emails))}
    assert "alpha@example.com" in normalized
    assert "sales@test.co" in normalized


def test_extract_emails_from_csv_file():
    csv_bytes = b"name,email\nJohn,john@example.com\nJane,jane@example.org\n"
    items = extract_emails_from_file(csv_bytes, "list.csv")
    assert len(items) >= 2
    assert any("row 2" in i["source"] for i in items)


def test_dedupe():
    items = [
        {"raw_email": "A@Test.com", "source": "paste"},
        {"raw_email": "a@test.com", "source": "paste"},
        {"raw_email": "b@test.com", "source": "paste"},
    ]
    out = normalize_and_dedupe(items)
    assert out["total"] == 3
    assert out["unique"] == 2
    assert out["duplicates"] == 1
    assert out["items"][1]["is_duplicate"] is True


def test_syntax_validation():
    assert is_valid_email_syntax("person@example.com")
    assert is_valid_email_syntax("first.last@sub.example.co")
    assert not is_valid_email_syntax("bad")
    assert not is_valid_email_syntax("bad@")
    assert not is_valid_email_syntax("@example.com")
    assert not is_valid_email_syntax("bad@-example.com")
    # Domain literal is not accepted for list validation.
    assert not is_valid_email_syntax("user@[127.0.0.1]")


def test_domain_format():
    assert is_valid_domain_format("example.com")
    assert is_valid_domain_format("sub.example.co")
    assert not is_valid_domain_format("example")
    assert not is_valid_domain_format("-example.com")
    assert not is_valid_domain_format("ex_ample.com")


def test_classify_role_and_disposable():
    assert classify_email("info@example.com", {"has_mx": True, "mx": ["mail.example.com"]})["status"] == "ROLE"
    assert classify_email("bob@mailinator.com", {"has_mx": True})["status"] == "DISPOSABLE"


def test_classify_dns_missing():
    result = classify_email("john@example.com", dns_result={"has_mx": False, "has_a": False, "error": None})
    assert result["status"] == "INVALID"


def test_classify_dns_error_is_unknown():
    result = classify_email(
        "john@example.com",
        dns_result={"has_mx": False, "has_a": False, "error": "LifetimeTimeout"},
    )
    assert result["status"] == "UNKNOWN"


def test_classify_valid_likely():
    result = classify_email(
        "john@example.com",
        dns_result={"has_mx": True, "mx": ["mx1.example.com", "mx2.example.com"], "has_a": True},
    )
    assert result["status"] == DELIVERABILITY_LIKELY
    assert "never" not in result["reason"].lower() or "does not prove" in result["reason"].lower()
