from io import BytesIO

from PIL import Image
from starlette.responses import Response, JSONResponse

from skipscale.exif_transpose import image_transpose_exif
from skipscale.utils import cache_url, cache_headers, make_request, should_allow_cors
from skipscale.config import Config

from sentry_sdk import Hub

async def imageinfo(request):
    """Return image dimensions, format and byte size."""

    tenant = request.path_params['tenant']
    image_uri = request.path_params['image_uri']
    config: Config = request.app.state.config

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    request_url = cache_url(
        request.app.state.config.cache_endpoint(),
        request.app.state.config.app_path_prefixes(),
        "original",
        tenant,
        image_uri
    )

    r = await make_request(request, request_url)
    # Technically imageinfo is ever only called internally so it doesn't need CORS headers to
    # function.. But the planner will set up headers for its user-facing 304/307 responses based on
    # the headers it receives from imageinfo, so we need to pass them through for its benefit here.
    output_headers = cache_headers(config.cache_control_override(tenant),
                                   config.cache_control_minimum(tenant),
                                   r,
                                   allow_cors=should_allow_cors(config.allow_cors(tenant), r))

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    i = Image.open(BytesIO(r.content))
    original_format = i.format
    i = image_transpose_exif(i)
    return JSONResponse({'width': i.width,
                         'height': i.height,
                         'format': original_format.lower(),
                         'bytes': len(r.content)},
                        headers=output_headers)
