import ipaddress

from rakit_core.config import RakitConfig
from rakit_core.errors import ErrorCode, RakitError

# A trusted-proxy CIDR wider than this is almost certainly a misconfiguration
# (e.g. "0.0.0.0/0") rather than an intentional load-balancer subnet -- reject
# it rather than silently trusting X-Forwarded-For from arbitrary peers.
_MAX_TRUSTED_PROXY_ADDRESSES = 2**16


def _invalid_production_config(reason: str, **details: object) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=f"Invalid production security configuration: {reason}",
        status_code=500,
        details={"reason": reason, **details},
    )


def validate_production_config(config: RakitConfig) -> None:
    """Fail closed at compile time for dangerous production settings.

    Only runs when `config.debug` is False. `RakitConfig` itself already
    requires a persistent `secret_key` in that case (see
    `RakitConfig.require_production_secret`) -- this adds the checks that
    depend on values a bare model validator on `RakitConfig` cannot express
    without duplicating `rakit-web`'s own security-header/CSP knowledge.
    """
    if config.debug:
        return
    if "*" in config.security.allowed_hosts:
        raise _invalid_production_config("wildcard_allowed_host")
    if not config.security.content_security_policy_enabled:
        raise _invalid_production_config("content_security_policy_disabled")
    for cidr in config.security.trusted_proxies:
        network = ipaddress.ip_network(cidr, strict=False)
        if network.num_addresses > _MAX_TRUSTED_PROXY_ADDRESSES:
            raise _invalid_production_config("overbroad_trusted_proxy", cidr=cidr)
