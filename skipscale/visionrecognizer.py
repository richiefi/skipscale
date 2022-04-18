from urllib.parse import urlencode

from httpx import RequestError, AsyncClient
from starlette.exceptions import HTTPException
from starlette.responses import Response, JSONResponse

from skipscale.utils import (
    cache_url,
    cache_headers_with_config,
    make_request,
    extract_forwardable_params,
)
from skipscale.config import Config

from sentry_sdk import Hub


async def visionrecognizer(request):
    """Return visionrecognizer data (saliency coordinates) for an image."""

    tenant = request.path_params["tenant"]
    image_uri = request.path_params["image_uri"]
    config: Config = request.app.state.config

    if (
        config.visionrecognizer_url() is None
        or config.visionrecognizer_bearer_token() is None
    ):
        raise HTTPException(500)

    if config.visionrecognizer_cache_endpoint() is not None:
        cache_endpoint = config.visionrecognizer_cache_endpoint()
    else:
        cache_endpoint = request.app.state.config.cache_endpoint()

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    _, fwd_q = extract_forwardable_params(dict(request.query_params))
    image_url = cache_url(
        cache_endpoint,
        request.app.state.config.app_path_prefixes(),
        None,
        tenant,
        image_uri,
        fwd_q,
    )

    query_params = urlencode(dict(url=image_url))
    outgoing_request_url = config.visionrecognizer_url() + "?" + query_params
    outgoing_request_headers = {
        "Authorization": "Bearer " + config.visionrecognizer_bearer_token()
    }

    client: AsyncClient = request.app.state.httpx_client
    req = client.build_request(
        "GET", outgoing_request_url, headers=outgoing_request_headers
    )
    try:
        r = await client.send(req)
    except RequestError:
        raise HTTPException(502)

    if r.is_error:
        raise HTTPException(r.status_code)

    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    return JSONResponse(r.json(), headers=output_headers)
