from http import HTTPStatus
import inspect
import ipaddress
from collections.abc import Iterable

from rakit_core.config import RakitConfig
from rakit_core.errors import ErrorCode, RakitError

# A trusted-proxy CIDR wider than this is almost certainly a misconfiguration
# (e.g. "0.0.0.0/0") rather than an intentional load-balancer subnet -- reject
# it rather than silently trusting X-Forwarded-For from arbitrary peers.
_MAX_TRUSTED_PROXY_ADDRESSES = 2**16

# 32 raw bytes of a persistent root secret is the same floor HKDF-SHA256
# derivation implicitly assumes for a well-distributed key (the KDF's
# output length in rakit_core.crypto). A shorter secret has less entropy
# than every key derived from it can actually provide.
_MIN_SECRET_BYTES = 32

TrustedProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _invalid_production_config(reason: str, **details: object) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=f"Invalid production security configuration: {reason}",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        details={"reason": reason, **details},
    )


def parse_trusted_proxy_networks(cidrs: Iterable[str]) -> tuple[TrustedProxyNetwork, ...]:
    """Parse trusted proxy CIDRs once, before any request can be served."""
    networks: list[TrustedProxyNetwork] = []
    for cidr in cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as error:
            raise _invalid_production_config("invalid_trusted_proxy") from error
    return tuple(networks)


def validate_production_config(
    config: RakitConfig,
    *,
    trusted_proxy_networks: tuple[TrustedProxyNetwork, ...] | None = None,
) -> None:
    """Fail closed at compile time for dangerous production settings.

    Only runs when `config.debug` is False. `RakitConfig` itself already
    requires a persistent `secret_key` in that case (see
    `RakitConfig.require_production_secret`) -- this adds the checks that
    depend on values a bare model validator on `RakitConfig` cannot express
    without duplicating `rakit-web`'s own security-header/CSP knowledge.
    """
    networks = (
        parse_trusted_proxy_networks(config.security.trusted_proxies)
        if trusted_proxy_networks is None
        else trusted_proxy_networks
    )
    if config.debug:
        return
    if "*" in config.security.allowed_hosts:
        raise _invalid_production_config("wildcard_allowed_host")
    if not config.security.content_security_policy_enabled:
        raise _invalid_production_config("content_security_policy_disabled")
    for cidr, network in zip(config.security.trusted_proxies, networks, strict=True):
        if network.num_addresses > _MAX_TRUSTED_PROXY_ADDRESSES:
            raise _invalid_production_config("overbroad_trusted_proxy", cidr=cidr)
    # `RakitConfig.require_production_secret` already guarantees a secret is
    # present when debug=False; this adds the strength check on top of that
    # presence check.
    secret_key = config.security.secret_key
    if secret_key is not None and len(secret_key.get_secret_value().encode()) < _MIN_SECRET_BYTES:
        raise _invalid_production_config("weak_secret_key")


def validate_rate_limiter_for_production(
    rate_limiter: object, *, debug: bool, auth_enabled: bool
) -> None:
    """Fail closed at `Admin` construction time when a non-production-safe
    rate limiter (the bundled in-memory `LoginRateLimiter`, or any other
    object that hasn't explicitly declared `production_safe = True`) would
    be used to gate login attempts in production.

    Only applies when both `debug=False` and authentication is actually
    configured -- an in-memory limiter is harmless in local development, and
    irrelevant if there's no login route to rate-limit in the first place.
    """
    if debug or not auth_enabled:
        return
    # `is True`, not truthiness: `production_safe = "yes"` is a mistake, and
    # accepting it would silently let a development limiter through.
    if getattr(rate_limiter, "production_safe", False) is not True:
        raise _invalid_production_config("development_only_rate_limiter")
    # The declaration is self-asserted, so also confirm the object can
    # actually be called the way `auth_routes` calls it. Otherwise the first
    # login attempt raises -- in production, on the request path, in the one
    # code path that is supposed to be holding an attacker back.
    check = getattr(rate_limiter, "check", None)
    if not callable(check) or not inspect.iscoroutinefunction(check):
        raise _invalid_production_config("rate_limiter_not_callable")
    try:
        inspect.signature(check).bind(admin_id="", identifier="", client_ip="")
    except TypeError as error:
        raise _invalid_production_config(
            "rate_limiter_not_callable", signature_error=str(error)
        ) from error


def validate_session_store_for_production(
    session_store: object, *, debug: bool, auth_enabled: bool
) -> None:
    """Reject process-local or malformed session stores before production serves."""
    if debug or not auth_enabled:
        return
    if getattr(session_store, "production_safe", False) is not True:
        raise _invalid_production_config("development_only_session_store")

    calls = {
        "create": (object(),),
        "resolve": ("",),
        "rotate": ("",),
        "revoke": ("",),
    }
    for method_name, arguments in calls.items():
        method = getattr(session_store, method_name, None)
        reason = f"session_store_{method_name}_not_callable"
        if not callable(method) or not inspect.iscoroutinefunction(method):
            raise _invalid_production_config(reason)
        try:
            inspect.signature(method).bind(*arguments)
        except (TypeError, ValueError) as error:
            raise _invalid_production_config(reason) from error


def validate_idempotency_store_for_production(store: object, *, debug: bool) -> None:
    """Require a durable, fully callable claim store before serving writes."""
    if debug:
        return
    if getattr(store, "production_safe", False) is not True:
        raise _invalid_production_config("development_only_idempotency_store")
    calls = {
        "begin": ("",),
        "complete": (object(), object()),
        "release": (object(),),
    }
    for method_name, arguments in calls.items():
        method = getattr(store, method_name, None)
        reason = f"idempotency_store_{method_name}_not_callable"
        if not callable(method) or not inspect.iscoroutinefunction(method):
            raise _invalid_production_config(reason)
        try:
            if method_name == "begin":
                inspect.signature(method).bind(*arguments, fingerprint="")
            else:
                inspect.signature(method).bind(*arguments)
        except (TypeError, ValueError) as error:
            raise _invalid_production_config(reason) from error
