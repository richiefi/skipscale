from starlette.exceptions import HTTPException
from starlette.responses import Response

from skipscale.urlcrypto import decrypt_url
from skipscale.utils import cache_headers, make_request, should_allow_cors, get_logger
from skipscale.config import Config

from sentry_sdk import Hub

log = get_logger(__name__)


async def original(request):
    """Return an image from the origin."""

    tenant = request.path_params['tenant']
    image_uri = request.path_params['image_uri']
    config: Config = request.app.state.config

    strip_regex = config.strip_regex(tenant)
    if strip_regex is not None:
        original_uri = image_uri
        image_uri = strip_regex.sub('', original_uri)
        if original_uri != image_uri:
            log.debug('strip_regex transformed image_uri %s -> %s',
                      original_uri, image_uri)

    origin = config.origin(tenant)
    if origin:
        request_url = origin + image_uri
    else:
        # If no origin is specified for the tenant, we expect encrypted urls.
        key = config.encryption_key(tenant)
        try:
            request_url = decrypt_url(key, tenant, image_uri.split('.')[0]) # omit file extension from encrypted url
        except:
            raise HTTPException(400)

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)
        span.set_tag("origin_url", request_url)

    # Allowed methods should be filtered on the Route level, we accept everything here
    method = request.method
    if method != 'GET':
        log.debug('forwarding %s request to %s', request.method, request_url)

    r = await make_request(request, request_url, proxy=config.proxy(tenant), method=method)
    output_headers = cache_headers(config.cache_control_override(tenant),
                                   config.cache_control_minimum(tenant),
                                   r,
                                   allow_cors=should_allow_cors(config.allow_cors(tenant), r))
    if 'content-type' in r.headers:
        output_headers['content-type'] = r.headers['content-type']
    # Since we're not streaming we know the real length.
    # Upstream content-length may include content-encoding, which is reversed by httpx.
    if method == 'HEAD':
        if 'content-length' in r.headers:
            # Since we don't have the actual data assume that it is what
            # the upstream tells us.
            output_headers['content-length'] = r.headers['content-length']
        return Response(None, status_code=r.status_code, headers=output_headers)
    output_headers['content-length'] = str(len(r.content))
    return Response(r.content, status_code=r.status_code, headers=output_headers)
