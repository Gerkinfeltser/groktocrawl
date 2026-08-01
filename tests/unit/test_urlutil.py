"""Unit tests for the shared URL utility module (common/url.py)."""

import pytest

from common.url import (
    _METADATA_IPS,
    _PRIVATE_HOSTNAME_SUFFIXES,
    _PRIVATE_NETWORKS,
    extract_domain,
    is_private_host,
    is_same_origin,
    normalize_url,
    validate_outbound_webhook_url,
)


class TestNormalizeUrl:
    def test_lowercases_scheme_and_host(self):
        assert normalize_url("HTTP://EXAMPLE.COM/Path") == "http://example.com/path"

    def test_strips_trailing_slash(self):
        assert normalize_url("http://example.com/path/") == "http://example.com/path"

    def test_preserves_root_slash(self):
        assert normalize_url("http://example.com/") == "http://example.com/"

    def test_sorts_query_params(self):
        result = normalize_url("http://example.com/?b=2&a=1&c=3")
        assert result == "http://example.com/?a=1&b=2&c=3"

    def test_preserves_fragment(self):
        assert (
            normalize_url("http://example.com/#section")
            == "http://example.com/#section"
        )

    def test_preserves_port(self):
        assert (
            normalize_url("http://example.com:8080/path")
            == "http://example.com:8080/path"
        )


class TestExtractDomain:
    def test_simple_hostname(self):
        assert extract_domain("http://example.com/path") == "example.com"

    def test_with_scheme(self):
        assert (
            extract_domain("https://example.com/path", include_scheme=True)
            == "https://example.com"
        )

    def test_empty_url(self):
        assert extract_domain("") == ""

    def test_relative_url(self):
        assert extract_domain("/path/to/page") == ""

    def test_ip_address(self):
        assert extract_domain("http://93.184.216.34/test") == "93.184.216.34"


class TestIsSameOrigin:
    def test_same_origin(self):
        assert is_same_origin("http://example.com/a", "http://example.com/b")

    def test_different_scheme(self):
        assert not is_same_origin("http://example.com/a", "https://example.com/b")

    def test_different_host(self):
        assert not is_same_origin("http://example.com/a", "http://other.com/b")

    def test_port_matters(self):
        assert not is_same_origin(
            "http://example.com:8080/a", "http://example.com:9090/b"
        )


class TestIsPrivateHost:
    def test_loopback(self):
        assert is_private_host("http://127.0.0.1/test")
        assert is_private_host("http://localhost/test")

    def test_rfc1918_10(self):
        assert is_private_host("http://10.0.0.1/test")

    def test_rfc1918_192_168(self):
        assert is_private_host("http://192.168.1.1/test")

    def test_rfc1918_172_16(self):
        assert is_private_host("http://172.16.0.1/test")

    def test_metadata_ip(self):
        assert is_private_host("http://169.254.169.254/latest/meta-data/")

    def test_public_host(self):
        assert not is_private_host("http://example.com/test")

    def test_public_ip(self):
        assert not is_private_host("http://93.184.216.34/test")  # example.com

    def test_link_local(self):
        assert is_private_host("http://169.254.1.1/test")

    def test_empty_url(self):
        assert is_private_host("")

    def test_relative_url(self):
        assert is_private_host("/relative/path")


class TestConstants:
    """Verify module-level constants are well-formed."""

    def test_private_networks_are_valid(self):
        for net in _PRIVATE_NETWORKS:
            # Just validate they parse — prefix lengths vary (/8, /16, /128, /7, /10)
            assert net.prefixlen > 0

    def test_metadata_ips_defined(self):
        assert len(_METADATA_IPS) >= 3

    def test_docker_hostname_suffixes(self):
        assert ".docker.internal" in _PRIVATE_HOSTNAME_SUFFIXES


class TestValidateOutboundWebhookUrl:
    """SSRF guard for outbound webhook destinations (issue #469)."""

    def test_accepts_public_https(self):
        assert validate_outbound_webhook_url("https://example.com/hook") is None

    def test_accepts_public_http(self):
        assert validate_outbound_webhook_url("http://example.com/hook") is None

    def test_accepts_public_ip(self):
        assert validate_outbound_webhook_url("https://93.184.216.34/hook") is None

    def test_rejects_missing_url(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("   ")

    def test_rejects_non_http_schemes(self):
        for bad in (
            "ftp://example.com/hook",
            "file:///etc/passwd",
            "gopher://example.com/hook",
            "//example.com/hook",  # scheme-less
            "example.com/hook",  # not a URL
        ):
            with pytest.raises(ValueError):
                validate_outbound_webhook_url(bad)

    def test_rejects_malformed_without_hostname(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("https:///path")

    def test_rejects_loopback(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://127.0.0.1:8080/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://localhost/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("https://[::1]/hook")

    def test_rejects_rfc1918(self):
        for host in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
            with pytest.raises(ValueError):
                validate_outbound_webhook_url(f"http://{host}/hook")

    def test_rejects_link_local_and_metadata(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://169.254.1.1/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_ipv6_ula_and_link_local(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("https://[fd00::1]/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("https://[fe80::1]/hook")

    def test_rejects_multicast(self):
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://224.0.0.1/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://239.255.255.250/hook")
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("https://[ff02::1]/hook")

    def test_rejects_docker_internal_hostname(self, monkeypatch):
        monkeypatch.setattr("common.url._resolve_to_ips", lambda hostname: [])
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://host.docker.internal:8080/hook")

    def test_rejects_hostname_resolving_to_private_ip(self, monkeypatch):
        from ipaddress import ip_address

        monkeypatch.setattr(
            "common.url._resolve_to_ips",
            lambda hostname: [ip_address("10.0.0.7")],
        )
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://public.example.com/hook")

    def test_rejects_hostname_resolving_to_metadata(self, monkeypatch):
        from ipaddress import ip_address

        monkeypatch.setattr(
            "common.url._resolve_to_ips",
            lambda hostname: [ip_address("169.254.169.254")],
        )
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://metadata.example.com/hook")

    def test_fails_closed_on_dns_failure(self, monkeypatch):
        monkeypatch.setattr("common.url._resolve_to_ips", lambda hostname: [])
        with pytest.raises(ValueError):
            validate_outbound_webhook_url("http://unresolvable.example.invalid/hook")

    def test_accepts_hostname_resolving_to_public_ip(self, monkeypatch):
        from ipaddress import ip_address

        monkeypatch.setattr(
            "common.url._resolve_to_ips",
            lambda hostname: [ip_address("93.184.216.34")],
        )
        assert validate_outbound_webhook_url("http://public.example.com/hook") is None
