"""Skipscale parsed configuration and validators."""

import os
import re
from typing import Any, List, Optional, Tuple, Dict

import schema
import validators
import toml

config_path = os.getenv('SKIPSCALE_CONFIG', "config.toml")

encryption_fields = {
    'key': schema.And(schema.Use(bytes.fromhex), lambda k: len(k) == 16),
    'username': str,
    'password': str,
    'url_prefix': schema.And(str, lambda s: s.endswith('/')),
    schema.Optional('asset_url_prefix'): schema.And(str, lambda s: s.endswith('/')),
}

tenant_overrideable_fields = {
    schema.Optional('default_quality'): int, # default 85
    schema.Optional('default_format'): schema.And(str,
                                                  schema.Use(str.lower),
                                                  lambda s: s in ('jpeg', 'png', 'webp')),
    schema.Optional('max_pixel_ratio'): int,
    schema.Optional('cache_control_override'): str,
    schema.Optional('encryption'): encryption_fields,
    schema.Optional('origin'): str,
    schema.Optional('proxy'): validators.url,
    schema.Optional('strip_regex'): schema.And(str,
                                               lambda s: re.compile(s) is not None)
}

main_fields = {
    schema.Optional('app_path_prefixes'): [schema.And(str, lambda s: s.endswith('/'))], # default ["/"]
    'cache_endpoint': schema.And(str, lambda s: s.endswith('/')),
    schema.Optional('origin_request_connect_timeout_seconds'): float,
    schema.Optional('origin_request_timeout_seconds'): float,
    schema.Optional('origin_request_max_keepalive_connections'): int,
    schema.Optional('origin_request_max_connections'): int,
    schema.Optional('origin_request_http2'): bool,
    schema.Optional('origin_request_local_address'): str,
    schema.Optional('sentry_dsn'): str,
    schema.Optional('sentry_traces_sample_rate'): float,
    schema.Optional('tenants'): {
        str: tenant_overrideable_fields
    }
}

config_schema = schema.Schema({**main_fields, **tenant_overrideable_fields})

class Config():
    """Server configuration parsed from a TOML file."""

    def __init__(self):
        with open(config_path) as f:
            parsed_config = toml.load(f)
        self.validated_config = config_schema.validate(parsed_config)

        self._strip_regex_cache: Dict[str, Any] = {}

    def _optional_main_optional_tenant(self, tenant: str, key: str) -> Any:
        if tenant in self.validated_config["tenants"] and key in self.validated_config["tenants"][tenant]:
            return self.validated_config["tenants"][tenant][key]
        elif key in self.validated_config:
            return self.validated_config[key]
        else:
            return None

    def app_path_prefixes(self) -> List[str]:
        if "app_path_prefixes" in self.validated_config:
            return self.validated_config["app_path_prefixes"]
        return ["/"]

    def cache_endpoint(self) -> str:
        return self.validated_config["cache_endpoint"]

    def origin_request_connect_timeout_seconds(self) -> float:
        if "origin_request_connect_timeout_seconds" in self.validated_config:
            return self.validated_config["origin_request_connect_timeout_seconds"]
        return 5.0

    def origin_request_timeout_seconds(self) -> float:
        if "origin_request_timeout_seconds" in self.validated_config:
            return self.validated_config["origin_request_timeout_seconds"]
        return 5.0

    def origin_request_max_keepalive_connections(self) -> Optional[int]:
        if "origin_request_max_keepalive_connections" in self.validated_config:
            if self.validated_config["origin_request_max_keepalive_connections"] > 0:
                return self.validated_config["origin_request_max_keepalive_connections"]
            return None
        return 10

    def origin_request_max_connections(self) -> Optional[int]:
        if "origin_request_max_connections" in self.validated_config:
            if self.validated_config["origin_request_max_connections"] > 0:
                return self.validated_config["origin_request_max_connections"]
            return None
        return 100

    def origin_request_http2(self) -> bool:
        if "origin_request_http2" in self.validated_config:
            return self.validated_config["origin_request_http2"]
        return False

    def origin_request_local_address(self) -> Optional[str]:
        if "origin_request_local_address" in self.validated_config:
            return self.validated_config["origin_request_local_address"]
        return None

    def sentry_dsn(self) -> Optional[str]:
        if "sentry_dsn" in self.validated_config:
            return self.validated_config["sentry_dsn"]
        return None

    def sentry_traces_sample_rate(self) -> float:
        if "sentry_traces_sample_rate" in self.validated_config:
            return self.validated_config["sentry_traces_sample_rate"]
        return 0.0

    def default_quality(self, tenant: str) -> int:
        default_quality = self._optional_main_optional_tenant(tenant, "default_quality")
        if not default_quality:
            return 85
        return default_quality

    def default_format(self, tenant: str) -> Optional[str]:
        """Default output image format. If not set, preserve the input format.
        Overridden by the `format` URL parameter."""

        default_format = self._optional_main_optional_tenant(tenant, "default_format")
        if not default_format:
            return None
        return default_format

    def cache_control_override(self, tenant: str) -> int:
        return self._optional_main_optional_tenant(tenant, "cache_control_override")

    def max_pixel_ratio(self, tenant: str) -> int:
        return self._optional_main_optional_tenant(tenant, "max_pixel_ratio")

    def encryption_key(self, tenant: str) -> Optional[bytes]:
        encryption = self._optional_main_optional_tenant(tenant, "encryption")
        if encryption:
            return encryption["key"]
        return None

    def encryption_credentials(self, tenant: str) -> Optional[Tuple[str, str]]:
        encryption = self._optional_main_optional_tenant(tenant, "encryption")
        if encryption:
            return encryption["username"], encryption["password"]
        return None

    def encryption_url_prefix(self, tenant: str) -> Optional[str]:
        """Returns the URL prefix used in encryption POST responses."""

        encryption = self._optional_main_optional_tenant(tenant, "encryption")
        if encryption:
            return encryption["url_prefix"]
        return None

    def encryption_asset_url_prefix(self, tenant: str) -> Optional[str]:
        """Returns the URL prefix used in encryption POST responses for asset
        (unscaled) URLs. Defaults to the value of `encryption_url_prefix`."""

        encryption = self._optional_main_optional_tenant(tenant, "encryption")
        if encryption and 'asset_url_prefix' in encryption:
            return encryption["asset_url_prefix"]
        return self.encryption_url_prefix(tenant)

    def origin(self, tenant: str) -> Optional[str]:
        """Returns a fixed origin for the tenant. If not set, the (encrypted)
        path from the request is used."""

        return self._optional_main_optional_tenant(tenant, "origin")

    def proxy(self, tenant: str) -> Optional[str]:
        """Returns an URL to a tenant-specific HTTP proxy if set. The
        URL can include basic auth credentials for the proxy."""

        return self._optional_main_optional_tenant(tenant, "proxy")

    def strip_regex(self, tenant: str):
        """Returns an optional (compiled) regular expression. Matches
        will be stripped from the path before it is sent to the origin."""

        try:
            return self._strip_regex_cache[tenant]
        except KeyError:
            pass

        re_str = self._optional_main_optional_tenant(tenant, "strip_regex")
        if not re_str:
            result = None
        else:
            result = re.compile(re_str)

        self._strip_regex_cache[tenant] = result
        return result
