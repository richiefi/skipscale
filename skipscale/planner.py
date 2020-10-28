from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.responses import Response, RedirectResponse

from skipscale.planner_math import plan_scale
from skipscale.utils import cache_url, cache_headers, make_request

from sentry_sdk import Hub

query_schema = Schema({
    Optional('width'): And(Use(int), lambda n: n > 0),
    Optional('height'): And(Use(int), lambda n: n > 0),
    Optional('dpr'): And(Use(int), lambda n: n > 0), # display pixel/point ratio
    Optional('quality'): And(Use(int), lambda n: 0 < n <= 100),
    Optional('mode'): And(str, Use(str.lower), lambda s: s in ('fit', 'crop', 'stretch')),
    Optional('format'): And(str, Use(str.lower), lambda s: s in ('jpeg', 'png', 'webp')),
    Optional('center-x'): And(Use(float), lambda n: 0.0 <= n <= 1.0),
    Optional('center-y'): And(Use(float), lambda n: 0.0 <= n <= 1.0),
}, ignore_extra_keys=True)

async def planner(request):
    """Redirect to a canonical url based on the request and the original image dimensions."""

    tenant = request.path_params['tenant']
    image_uri = request.path_params['image_uri']

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    try:
        q = query_schema.validate(dict(request.query_params))
    except:
        raise HTTPException(400, "invalid set of query parameters")
    
    if ('center-x' in q and 'center-y' not in q) or ('center-y' in q and 'center-x' not in q):
        raise HTTPException(400, "both center-x and center-y required")

    if 'center-x' in q and ('width' not in q or 'height' not in q):
        raise HTTPException(400, "both width and height are required when cropping")

    imageinfo_url = cache_url(
        request.app.state.config.cache_endpoint(),
        request.app.state.config.app_path_prefixes(),
        "imageinfo",
        tenant,
        image_uri
    )
    r = await make_request(request, imageinfo_url)
    output_headers = cache_headers(request.app.state.config.cache_control_override(tenant), r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    imageinfo = r.json()

    scale_params = plan_scale(q, imageinfo, request.app.state.config.max_pixel_ratio(tenant))

    if 'quality' in q:
        scale_params['quality'] = q['quality']
    else:
        scale_params['quality'] = request.app.state.config.default_quality(tenant)

    if 'format' in q:
        scale_params['format'] = q['format']
    else:
        scale_params['format'] = imageinfo['format']

    if (
        (scale_params['width'] == imageinfo['width'] and scale_params['height'] == imageinfo['height'] and scale_params['format'] == imageinfo['format'] and 'quality' not in q)
        or
        (imageinfo['format'] == "gif" and scale_params['format'] == "gif") # We don't process GIFs unless format conversion is explicitly requested
       ):
        # The request is best served by the original image, so redirect straight to that.
        original_url = cache_url(
            None, # Get relative URL for redirect
            request.app.state.config.app_path_prefixes(),
            "original",
            tenant,
            image_uri,
        )
        return RedirectResponse(original_url, headers=output_headers)

    scale_url = cache_url(
        None, # Get relative URL for redirect
        request.app.state.config.app_path_prefixes(),
        "scale",
        tenant,
        image_uri,
        scale_params
    )
    return RedirectResponse(scale_url, headers=output_headers)