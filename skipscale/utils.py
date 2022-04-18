"""Miscellaneous utility functions."""

import logging
import copy
from urllib.parse import urljoin, urlencode
from typing import Optional, Union, Dict, List, Tuple

from httpx import RequestError, AsyncClient
import sentry_sdk
from starlette.exceptions import HTTPException
from starlette.requests import Request


def get_logger(*components) -> logging.Logger:
    """Get a logger under the app's hierarchy."""

    name = ".".join(["skipscale"] + list(components))
    return logging.getLogger(name)


def cache_url(
    cache_endpoint, app_path_prefixes, url_type, tenant, image_uri, params=None
) -> str:
    app_prefix = urljoin(cache_endpoint, app_path_prefixes[0])
    if url_type is not None:
        url = urljoin(app_prefix, url_type + "/" + tenant + "/" + image_uri)
    else:
        url = urljoin(app_prefix, tenant + "/" + image_uri)
    if params:
        url = urljoin(url, "?" + urlencode(params, safe=","))
    return url


async def make_request(
    incoming_request: Request,
    outgoing_request_url: str,
    stream=False,
    method="GET",
    proxy: Optional[str] = None,
    follow_redirects=False,
):
    log = get_logger("utils", "make_request")

    outgoing_request_headers = {}

    def fwd_header(name, do_log=False) -> None:
        if name in incoming_request.headers:
            outgoing_request_headers[name] = incoming_request.headers[name]
            if do_log:
                log.debug(
                    "forwarding downstream %s: %s", name, outgoing_request_headers[name]
                )

    fwd_header("if-modified-since")
    fwd_header("if-none-match")
    fwd_header("origin", do_log=True)
    fwd_header("access-control-request-method")
    fwd_header("access-control-request-headers")

    close_client = False
    client = incoming_request.app.state.httpx_client

    # httpx proxy settings are per-client, if one is set we need to create a new one
    # instead of using the global instance. This assumes that proxy usage is limited
    # to test/QA feeds.
    if proxy:
        close_client = True
        client = AsyncClient(timeout=client.timeout, proxies=proxy)
        log.debug("fetching %s through proxy", outgoing_request_url)

    req = client.build_request(
        method, outgoing_request_url, headers=outgoing_request_headers
    )
    try:
        r = await client.send(req, stream=stream, follow_redirects=follow_redirects)
    except RequestError:
        raise HTTPException(502)
    finally:
        if close_client:
            await client.aclose()

    if r.is_error:
        raise HTTPException(r.status_code)

    if method == "GET" and r.status_code != 304 and not r.content:
        # No error, but we got no response body.
        sentry_sdk.set_context(
            "outbound_request",
            {
                "request_url": outgoing_request_url,
                "request_headers": outgoing_request_headers,
                "response_headers": r.headers,
            },
        )
        raise RuntimeError("empty body from upstream")

    return r


# Shortcut for the most common type of cache_headers invocation
def cache_headers_with_config(config, tenant: str, received_response) -> Dict[str, str]:
    return cache_headers(
        config.cache_control_override(tenant),
        config.cache_control_minimum(tenant),
        config.allow_cors(tenant),
        received_response,
    )


def cache_headers(
    cache_control_override: Optional[str],
    cache_control_minimum: Optional[str],
    force_cors: bool,
    received_response,
) -> Dict[str, str]:
    output_headers: Dict[str, str] = {}
    if "last-modified" in received_response.headers:
        output_headers["last-modified"] = received_response.headers["last-modified"]
    if "etag" in received_response.headers:
        output_headers["etag"] = received_response.headers["etag"]
    if cache_control_override:
        output_headers["cache-control"] = cache_control_override
    elif cache_control_minimum:
        received_cc = ParsedCacheControl(received_response.headers.get("cache-control"))
        reference_cc = ParsedCacheControl(cache_control_minimum)
        new_cc = str(received_cc.merge(reference_cc))
        if new_cc:
            output_headers["cache-control"] = new_cc
    else:
        if "cache-control" in received_response.headers:
            output_headers["cache-control"] = received_response.headers["cache-control"]
        if "expires" in received_response.headers:
            output_headers["expires"] = received_response.headers["expires"]
        if "pragma" in received_response.headers:
            output_headers["pragma"] = received_response.headers["pragma"]

    allow_cors = should_allow_cors(force_cors, received_response)
    if allow_cors:
        if isinstance(allow_cors, str):
            output_headers["access-control-allow-origin"] = allow_cors
        elif isinstance(allow_cors, dict):
            output_headers.update(allow_cors)
        else:
            output_headers["access-control-allow-origin"] = "*"
        final_acao = output_headers.get("access-control-allow-origin")
        # See https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Access-Control-Allow-Origin#CORS_and_caching
        if final_acao and final_acao != "*":
            output_headers["vary"] = "origin"
    return output_headers


def should_allow_cors(force_flag: bool, upstream_response) -> Union[dict, bool]:
    log = get_logger("utils", "should_allow_cors")

    # If force is set in configuration, always return ACAO=*
    if force_flag:
        log.debug("forcing ACAO")
        return True

    # Check if upstream returned ACAO and pass it on if it did
    if (
        upstream_response is not None
        and "access-control-allow-origin" in upstream_response.headers
    ):
        acao = upstream_response.headers["access-control-allow-origin"]
        addl_headers: Dict[str, str] = {"access-control-allow-origin": acao}

        if "access-control-allow-method" in upstream_response.headers:
            addl_headers["access-control-allow-method"] = upstream_response.headers[
                "access-control-allow-method"
            ]
        if "access-control-allow-headers" in upstream_response.headers:
            addl_headers["access-control-allow-headers"] = upstream_response.headers[
                "access-control-allow-headers"
            ]

        log.debug("forwarding upstream ACAO: %s", acao)
        return acao

    return False


def is_safe_path(path: str) -> bool:
    """Checks whether the given path attempts traversal with /. Returns True
    if path is safe, False otherwise."""

    is_safe = True
    new_comps: List[str] = []
    for comp in path.split("/"):
        if not comp or comp == ".":
            continue

        if comp == "..":
            try:
                new_comps.pop(-1)
            except IndexError:
                # Tried to move past /
                is_safe = False
            continue

        new_comps.append(comp)

    return is_safe


# This should contain parameters that typically indicate the version of a mutable
# resource. This allows scaling efficiently caching paths such as /foo.jpg?v=ab1234
# where contents of foo.jpg may change but the change will be reflected by a changed
# query string in some container. These parameters must not overlap with scaling-related
# parameters.
FORWARDABLE_PARAMS = ("v", "hash")


def extract_forwardable_params(
    q_params: Dict[str, str]
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Extract parameters that should be forwarded to subsequent requests
    or the origin from a query string. Modifies the dictionary passed in,
    returns the extracted parameters as a new dictionary."""

    result: Dict[str, str] = {}
    for key in FORWARDABLE_PARAMS:
        try:
            result[key] = q_params.pop(key)
        except KeyError:
            pass

    return q_params, result


class ParsedCacheControl:
    """A parsed representation of a Cache-Control header."""

    def __init__(self, header: Optional[str]) -> None:
        self.is_present = False

        self.storage: Optional[str] = None
        self.max_age: Optional[int] = None
        self.s_maxage: Optional[int] = None
        self.stale_error: Optional[int] = None
        self.stale_revalidate: Optional[int] = None
        self.other: List[Tuple[str, Optional[str]]] = []

        self._log = get_logger("utils", "ParsedCacheControl")

        if header is None:
            return

        try:
            self._parse_header(header)
        except Exception:
            self._log.exception("failed to parse Cache-Control header %r", header)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} present={self.is_present} header={str(self)!r}>"

    # Special max_age to signal "immutable"
    IMMUTABLE_AGE = 2**31
    MAX_AGE = IMMUTABLE_AGE - 1

    def __str__(self) -> str:
        if not self.is_present:
            return ""

        comps: List[str] = []
        if self.storage:
            comps.append(self.storage)
        if self.is_immutable:
            comps.append("immutable")
        else:
            if self.max_age is not None:
                comps.append(f"max-age={self.max_age}")
            if self.s_maxage is not None:
                comps.append(f"s-maxage={self.s_maxage}")
        if self.stale_error is not None:
            comps.append(f"stale-if-error={self.stale_error}")
        if self.stale_revalidate is not None:
            comps.append(f"stale-while-revalidate={self.stale_revalidate}")
        for other_key, other_value in self.other:
            if other_value is None:
                comps.append(other_key)
                continue

            comps.append("f{other_key}={other_value}")

        return ", ".join(comps)

    @property
    def is_immutable(self):
        if self.max_age is None:
            return False

        return self.max_age >= self.IMMUTABLE_AGE

    def _parse_header(self, header: str) -> None:
        header = header.strip()
        if not header:
            return

        self.is_present = True

        def parse_number(val: Optional[str]) -> Optional[int]:
            if val is None:
                # Item was missing the time argument
                return None

            try:
                # Allow floats but discard fractional part
                num = int(float(val))
                # Reject negative
                if num < 0:
                    raise ValueError("negative value")
                # Clamp to a sane value
                if num > self.MAX_AGE:
                    num = self.MAX_AGE
                return num
            except (TypeError, ValueError):
                return None

        for comp in header.split(","):
            comp = comp.strip()
            if not comp:
                continue

            value: Optional[str]
            if "=" in comp:
                comp, value = comp.split("=", 1)
            else:
                value = None

            if comp in ("public", "private", "no-cache", "no-store"):
                self.storage = comp
            elif comp == "max-age":
                self.max_age = parse_number(value)
            elif comp == "s-maxage":
                self.s_maxage = parse_number(value)
            elif comp == "stale-if-error":
                self.stale_error = parse_number(value)
            elif comp == "stale-while-revalidate":
                self.stale_revalidate = parse_number(value)
            elif comp == "immutable":
                # Indicate this using a special max_age. Simplifies comparisons
                # and allows later max-age directives to override.
                self.max_age = self.IMMUTABLE_AGE
                self.s_maxage = None
            else:
                self.other.append((comp, value))

    def copy(self) -> "ParsedCacheControl":
        return copy.deepcopy(self)

    def merge(self, other: "ParsedCacheControl") -> "ParsedCacheControl":
        """Merge max-age values from `other` to this instance if they are
        longer than in this one."""

        if not self.is_present:
            return other

        def safe_le(a: Optional[int], b: Optional[int]) -> bool:
            if a is None and b is None:
                return False

            if a is None and b is not None:
                return True

            if a is not None and b is None:
                return False

            return a < b  # type: ignore

        def merge_field(key):
            a = getattr(self, key)
            b = getattr(other, key)
            if safe_le(a, b):
                setattr(self, key, b)

        merge_field("max_age")
        merge_field("s_maxage")
        merge_field("stale_revalidate")
        merge_field("stale_error")

        if self.storage is None:
            self.storage = other.storage

        return self
