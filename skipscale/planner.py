from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse

from skipscale.planner_math import plan_scale
from skipscale.utils import (
    cache_url,
    cache_headers_with_config,
    make_request,
    get_logger,
    extract_forwardable_params,
)
from skipscale.config import Config

from sentry_sdk import Hub

# Image formats which will not be scaled by default
NONSCALED_FORMATS = frozenset(('gif', 'png'))

log = get_logger(__name__)

dimensions_fields = {
    Optional("width"): And(Use(int), lambda n: n >= 0),
    Optional("height"): And(Use(int), lambda n: n >= 0),
    Optional("dpr"): And(Use(int), lambda n: n > 0),  # display pixel/point ratio
    Optional("mode"): And(
        str, Use(str.lower), lambda s: s in ("fit", "crop", "stretch")
    ),
    Optional("center_x"): And(Use(float), lambda n: 0.0 <= n <= 1.0),
    Optional("center_y"): And(Use(float), lambda n: 0.0 <= n <= 1.0),
}

additional_fields = {
    Optional("size"): And(Use(int), lambda n: n >= 0),
    Optional("quality"): And(Use(int), lambda n: 0 < n <= 100),
    Optional("format"): And(
        str, Use(str.lower), lambda s: s in ("jpeg", "png", "webp")
    ),
}

dimensions_schema = Schema(
    dimensions_fields,
    ignore_extra_keys=True,
)

query_schema = Schema(
    dimensions_fields | additional_fields,
    ignore_extra_keys=True,
)


async def planner(request: Request):
    """Redirect to a canonical url based on the request and the original image dimensions."""

    tenant = request.path_params["tenant"]
    image_uri = request.path_params["image_uri"]
    config: Config = request.app.state.config

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    in_q, fwd_q = extract_forwardable_params(dict(request.query_params))
    if "center-x" in in_q:
        in_q["center_x"] = in_q.pop("center-x")
    if "center-y" in in_q:
        in_q["center_y"] = in_q.pop("center-y")

    try:
        q = query_schema.validate(in_q)
    except Exception:
        log.warning("invalid query parameters (planner) in request %s", request.url)
        raise HTTPException(400, "invalid set of query parameters")

    # size is a shortcut to set width/height to the same size and force fit mode
    box_size = q.pop("size", 0)
    if box_size > 0:
        q["width"] = q["height"] = box_size
        q["mode"] = "fit"

    # If width or height are set but zero, behave as if they weren't specified
    if "width" in q and q["width"] == 0:
        del q["width"]
    if "height" in q and q["height"] == 0:
        del q["height"]

    # If mode=stretch but one of the dimensions is not set, force mode=fit
    if q.get("mode") == "stretch":
        if "width" not in q or "height" not in q:
            q["mode"] = "fit"

    if ("center_x" in q and "center_y" not in q) or (
        "center_y" in q and "center_x" not in q
    ):
        raise HTTPException(400, "both center_x and center_y required")

    if "mode" not in q and "center_x" in q:
        q["mode"] = "crop"

    if q.get("mode") == "crop" and ("width" not in q or "height" not in q):
        raise HTTPException(400, "both width and height are required when cropping")

    imageinfo_url = cache_url(
        config.cache_endpoint(),
        config.app_path_prefixes(),
        "imageinfo",
        tenant,
        image_uri,
        fwd_q,
    )
    r = await make_request(request, imageinfo_url)
    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    imageinfo = r.json()

    if imageinfo["format"] == "svg":
        if q.get("mode") == "crop" or "format" in q:
            raise HTTPException(400, "cannot crop or convert SVG images")
        # The request is best served by the original image, so redirect straight to that.
        original_url = cache_url(
            None,  # Get relative URL for redirect
            config.app_path_prefixes(),
            "original",
            tenant,
            image_uri,
            fwd_q,
        )
        log.debug(
            "redirecting to original request %s with input path %s",
            original_url,
            request.url.path,
        )
        return RedirectResponse(original_url, headers=output_headers)

    if (
        "mode" in q
        and (q["mode"] == "crop" and "center_x" not in q)
        and config.visionrecognizer_url() is not None
    ):
        # Crop requested but center point not specified. Perform feature detection.
        visionrecognizer_url = cache_url(
            config.cache_endpoint(),
            config.app_path_prefixes(),
            "visionrecognizer",
            tenant,
            image_uri,
            fwd_q,
        )
        try:
            r = await make_request(request, visionrecognizer_url)
            if r.status_code == 304:
                return Response(status_code=304, headers=output_headers)
            visionrecognizer_result = r.json()
            q["center_x"] = visionrecognizer_result["centerPoint"]["x"]
            q["center_y"] = (
                1.0 - visionrecognizer_result["centerPoint"]["y"]
            )  # visionrecognizer has a flipped y-axis
        except Exception:
            # the downstream code defaults to center crop
            pass

    scale_dimensions = plan_scale(
        imageinfo["width"],
        imageinfo["height"],
        max_pixel_ratio=config.max_pixel_ratio(tenant),
        **dimensions_schema.validate(q),
    )
    size_identical = (
        scale_dimensions.width == imageinfo["width"]
        and scale_dimensions.height == imageinfo["height"]
    )

    if "quality" in q:
        quality = q["quality"]
    else:
        quality = config.default_quality(tenant)

    default_format = config.default_format(tenant)
    is_nonscaled_source = imageinfo['format'] in NONSCALED_FORMATS

    if "format" in q:
        format = q["format"]
    elif default_format and not size_identical and not is_nonscaled_source:
        # Convert to default format if scaling, otherwise
        # allow grabbing the original size & format.
        #
        # Exception: if the original format is one of NONSCALED_FORMATS
        # and an explicit target format is _not_ requested, then don't switch
        # format to default. This prevents mangling graphics PNGs And
        # animated GIFs if default_format is set.
        format = default_format
    else:
        format = imageinfo["format"]

    if (size_identical and format == imageinfo["format"] and "quality" not in q) or \
       (is_nonscaled_source and format in NONSCALED_FORMATS):
        # The request is best served by the original image, so redirect straight to that.
        # This happens if either:
        # a) no scaling or format/quality conversion would happen, or
        # b) both the source and target formats are non-scaleable (see comment above).
        original_url = cache_url(
            None,  # Get relative URL for redirect
            config.app_path_prefixes(),
            "original",
            tenant,
            image_uri,
            fwd_q,
        )
        log.debug(
            "redirecting to original request %s with input path %s",
            original_url,
            request.url.path,
        )
        return RedirectResponse(original_url, headers=output_headers)

    scale_params = {
        "width": scale_dimensions.width,
        "height": scale_dimensions.height,
        "crop": f"{scale_dimensions.source_x},{scale_dimensions.source_y},{scale_dimensions.source_x2},{scale_dimensions.source_y2}",
        "quality": quality,
        "format": format,
    }
    scale_url = cache_url(
        None,  # Get relative URL for redirect
        config.app_path_prefixes(),
        "scale",
        tenant,
        image_uri,
        scale_params | fwd_q,
    )
    log.debug(
        "redirecting to scale request %s with input path %s",
        scale_url,
        request.url.path,
    )
    return RedirectResponse(scale_url, headers=output_headers)
