from io import BytesIO

from PIL import Image
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from skipscale.exif_transpose import image_transpose_exif
from skipscale.utils import (
    cache_url,
    cache_headers_with_config,
    make_request,
    extract_forwardable_params,
)
from skipscale.config import Config

from sentry_sdk import Hub


async def imageinfo(request: Request):
    """Return image dimensions, format and byte size."""

    tenant = request.path_params["tenant"]
    image_uri = request.path_params["image_uri"]
    config: Config = request.app.state.config

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    _, fwd_q = extract_forwardable_params(dict(request.query_params))
    request_url = cache_url(
        request.app.state.config.cache_endpoint(),
        request.app.state.config.app_path_prefixes(),
        "original",
        tenant,
        image_uri,
        fwd_q,
    )

    r = await make_request(request, request_url)
    # Technically imageinfo is ever only called internally so it doesn't need CORS headers to
    # function... but the planner will set up headers for its user-facing 304/307 responses based on
    # the headers it receives from imageinfo, so we need to pass them through for its benefit here.
    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    i = Image.open(BytesIO(r.content))
    original_format = i.format
    i = image_transpose_exif(i)
    return JSONResponse(
        {
            "width": i.width,
            "height": i.height,
            "format": original_format.lower(),
            "bytes": len(r.content),
        },
        headers=output_headers,
    )
