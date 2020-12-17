from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.responses import Response, RedirectResponse

from skipscale.planner_math import plan_scale
from skipscale.utils import cache_url, cache_headers_with_config, make_request, get_logger, \
    extract_forwardable_params
from skipscale.config import Config

from sentry_sdk import Hub

log = get_logger(__name__)

query_schema = Schema({
    Optional('width'): And(Use(int), lambda n: n >= 0),
    Optional('height'): And(Use(int), lambda n: n >= 0),
    Optional('size'): And(Use(int), lambda n: n >= 0),
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
    config: Config = request.app.state.config

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    in_q, fwd_q = extract_forwardable_params(dict(request.query_params))
    try:
        q = query_schema.validate(in_q)
    except Exception:
        log.warning('invalid query parameters (planner) in request %s', request.url)
        raise HTTPException(400, "invalid set of query parameters")

    # size is a shortcut to set width/height to the same size and force fit mode
    box_size = q.pop('size', 0)
    if box_size > 0:
        q['width'] = q['height'] = box_size
        q['mode'] = 'fit'

    # If width or height are set but zero, behave as if they weren't specified
    if 'width' in q and q['width'] == 0:
        del q['width']
    if 'height' in q and q['height'] == 0:
        del q['height']

    if ('center-x' in q and 'center-y' not in q) or ('center-y' in q and 'center-x' not in q):
        raise HTTPException(400, "both center-x and center-y required")

    if 'center-x' in q and ('width' not in q or 'height' not in q):
        raise HTTPException(400, "both width and height are required when cropping")

    imageinfo_url = cache_url(
        config.cache_endpoint(),
        config.app_path_prefixes(),
        "imageinfo",
        tenant,
        image_uri,
        fwd_q
    )
    r = await make_request(request, imageinfo_url)
    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    imageinfo = r.json()

    scale_params = plan_scale(q, imageinfo, config.max_pixel_ratio(tenant))
    scaling_requested = 'width' in q or 'height' in q
    size_identical = scale_params['width'] == imageinfo['width'] and \
        scale_params['height'] == imageinfo['height']

    if 'quality' in q:
        scale_params['quality'] = q['quality']
    else:
        scale_params['quality'] = config.default_quality(tenant)

    default_format = config.default_format(tenant)
    if 'format' in q:
        scale_params['format'] = q['format']
    elif default_format and scaling_requested:
        # Convert to default format if scaling requested, but otherwise allow grabbing
        # the original size & format.
        scale_params['format'] = default_format
    else:
        scale_params['format'] = imageinfo['format']

    if (
        (size_identical and scale_params['format'] == imageinfo['format'] and 'quality' not in q)
        or
        (imageinfo['format'] == "gif" and scale_params['format'] == "gif") # We don't process GIFs or PNGs unless format conversion is explicitly requested
        or
        (imageinfo['format'] == "png" and scale_params['format'] == "png")
       ):
        # The request is best served by the original image, so redirect straight to that.
        original_url = cache_url(
            None, # Get relative URL for redirect
            config.app_path_prefixes(),
            "original",
            tenant,
            image_uri,
            fwd_q
        )
        log.debug('redirecting to original request %s with input path %s',
                  original_url, request.url.path)
        return RedirectResponse(original_url, headers=output_headers)

    scale_params.update(fwd_q)
    scale_url = cache_url(
        None, # Get relative URL for redirect
        config.app_path_prefixes(),
        "scale",
        tenant,
        image_uri,
        scale_params
    )
    log.debug('redirecting to scale request %s with input path %s', scale_url, request.url.path)
    return RedirectResponse(scale_url, headers=output_headers)
