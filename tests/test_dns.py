from dns_lookup import lookup_domain


def test_lookup_gmail_mx():
    result = lookup_domain("gmail.com", timeout=3, retries=0)
    # 'gmail.com' should have MX records in a working internet environment.
    assert result["has_mx"] is True
    assert len(result["mx"]) > 0


def test_lookup_example_com():
    result = lookup_domain("example.com", timeout=3, retries=0)
    # example.com is a reserved domain but has meaningful DNS data.
    assert result["error"] is None
