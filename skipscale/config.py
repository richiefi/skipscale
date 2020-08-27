import os
from typing import Any, List, Optional, Tuple, Union

import schema
import toml

config_path = os.getenv('SKIPSCALE_CONFIG', "config.toml")

encryption_fields = {
    'key': schema.And(schema.Use(bytes.fromhex), lambda k: len(k) == 16),
    'username': str,
    'password': str,
    'url_prefix': schema.And(str, lambda s: s.endswith('/')),
}

tenant_overrideable_fields = {
    schema.Optional('default_quality'): int, # default 85
    schema.Optional('max_pixel_ratio'): int,
    schema.Optional('cache_control_override'): str,
    schema.Optional('encryption'): encryption_fields,
    schema.Optional('origin'): str,
}

main_fields = {
    'cache_endpoint': schema.And(str, lambda s: s.endswith('/')),
    schema.Optional('sentry_dsn'): str,
    schema.Optional('app_path_prefixes'): [schema.And(str, lambda s: s.endswith('/'))], # default ["/"]
    schema.Optional('tenants'): {
        str: tenant_overrideable_fields
    }
}

config_schema = schema.Schema({**main_fields, **tenant_overrideable_fields})

class Config():
    def __init__(self):
        with open(config_path) as f:
            parsed_config = toml.load(f)
        self.validated_config = config_schema.validate(parsed_config)

    def _optional_main_optional_tenant(self, tenant: str, key: str) -> Any:
        if tenant in self.validated_config["tenants"] and key in self.validated_config["tenants"][tenant]:
            return self.validated_config["tenants"][tenant][key]
        elif key in self.validated_config:
            return self.validated_config[key]
        else:
            return None          

    def cache_endpoint(self) -> str:
        return self.validated_config["cache_endpoint"]

    def app_path_prefixes(self) -> List[str]:
        if "app_path_prefixes" in self.validated_config:
            return self.validated_config["app_path_prefixes"]
        return ["/"]

    def sentry_dsn(self) -> Optional[str]:
        if "sentry_dsn" in self.validated_config:
            return self.validated_config["sentry_dsn"]
        return None

    def default_quality(self, tenant: str) -> int:
        default_quality = self._optional_main_optional_tenant(tenant, "default_quality")
        if not default_quality:
            return 85
        return default_quality

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

    def encryption_url_prefix(self, tenant: str) -> Optional[bytes]:
        encryption = self._optional_main_optional_tenant(tenant, "encryption")
        if encryption:
            return encryption["url_prefix"]
        return None

    def origin(self, tenant: str) -> Optional[str]:
        return self._optional_main_optional_tenant(tenant, "origin")
