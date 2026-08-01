import ipaddress

import pytest
from rakit import Admin
from rakit_core.errors import RakitError
from rakit_web.security import validation
from rakit_web.security.middleware import resolve_client_ip
from starlette.requests import Request


def _request(*, peer: str, forwarded_for: str | None = None) -> Request:
    headers = [(b"host", b"localhost")]
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/auth/login",
            "raw_path": b"/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("localhost", 80),
        }
    )


def _networks(*values: str):
    return tuple(ipaddress.ip_network(value) for value in values)


def test_append_style_proxy_uses_nearest_untrusted_hop_not_attacker_prefix() -> None:
    request = _request(peer="10.0.0.9", forwarded_for="198.51.100.4, 203.0.113.8")
    assert resolve_client_ip(request, _networks("10.0.0.0/24")) == "203.0.113.8"


def test_one_trusted_proxy_selects_forwarded_client() -> None:
    request = _request(peer="10.0.0.9", forwarded_for="203.0.113.8")
    assert resolve_client_ip(request, _networks("10.0.0.0/24")) == "203.0.113.8"


def test_multiple_trusted_proxy_hops_are_removed_right_to_left() -> None:
    request = _request(peer="10.0.0.9", forwarded_for="198.51.100.7, 10.1.0.8, 10.0.0.8")
    assert resolve_client_ip(request, _networks("10.0.0.0/24", "10.1.0.0/24")) == "198.51.100.7"


def test_untrusted_direct_peer_ignores_forwarded_chain() -> None:
    request = _request(peer="192.0.2.10", forwarded_for="203.0.113.8")
    assert resolve_client_ip(request, _networks("10.0.0.0/24")) == "192.0.2.10"


@pytest.mark.parametrize("forwarded_for", ["attacker", "999.999.999.999", "1.2.3.4, bad"])
def test_malformed_forwarded_chain_falls_back_to_canonical_direct_peer(
    forwarded_for: str,
) -> None:
    request = _request(peer="10.0.0.9", forwarded_for=forwarded_for)
    assert resolve_client_ip(request, _networks("10.0.0.0/24")) == "10.0.0.9"


def test_ipv6_is_canonicalized_for_stable_limiter_buckets() -> None:
    expanded = _request(peer="2001:db8:0:0:0:0:0:1")
    compressed = _request(peer="2001:db8::1")
    assert resolve_client_ip(expanded, ()) == "2001:db8::1"
    assert resolve_client_ip(compressed, ()) == "2001:db8::1"


@pytest.mark.parametrize("debug", [True, False])
def test_invalid_trusted_proxy_cidr_fails_during_admin_construction(debug: bool) -> None:
    kwargs = {"title": "Operations", "debug": debug, "trusted_proxies": ("not-a-cidr",)}
    if not debug:
        from rakit import SecretValue

        kwargs["secret_key"] = SecretValue("x" * 32)
    with pytest.raises(RakitError) as exc_info:
        Admin(**kwargs)
    assert exc_info.value.details["reason"] == "invalid_trusted_proxy"


def test_trusted_proxy_networks_are_parsed_once_into_immutable_objects() -> None:
    assert hasattr(validation, "parse_trusted_proxy_networks")
    parsed = validation.parse_trusted_proxy_networks(("10.0.0.1/24", "2001:db8::1/64"))
    assert parsed == (
        ipaddress.ip_network("10.0.0.0/24"),
        ipaddress.ip_network("2001:db8::/64"),
    )
