import asyncio
import concurrent.futures
import functools

from pyvips import Image
from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from skipscale.utils import (
    cache_url,
    cache_headers_with_config,
    make_request,
    get_logger,
    extract_forwardable_params,
    vips_format_from_loader,
)
from skipscale.config import Config

from sentry_sdk import Hub

log = get_logger(__name__)


def blocking_scale(content, q):
    i = Image.new_from_buffer(content, "")
    i = i.autorot()  # rotate based on EXIF orientation
    original_format = vips_format_from_loader(i)
    if q["crop"]:
        crop_left, crop_top, crop_right, crop_bottom = q["crop"]
        crop_width = crop_right - crop_left
        crop_height = crop_bottom - crop_top
        i = i.extract_area(crop_left, crop_top, crop_width, crop_height)
    i = i.thumbnail_image(q["width"], height=q["height"], size="both", linear=False)
    match q["format"].lower():
        case "jpeg":
            return i.jpegsave_buffer(
                Q=q["quality"],
                optimize_coding=True,
                interlace=True,
                trellis_quant=True,
                overshoot_deringing=True,
                optimize_scans=True,
                quant_table=3,
                subsample_mode="auto",  # with this, chroma subsampling is disabled with quality >= 90
                strip=True,
            )
        case "png":
            return i.pngsave_buffer(
                compression=9,  # max
                effort=10,  # max
                strip=True,
            )
        case "webp":
            return i.webpsave_buffer(
                lossless=(original_format == "png"),
                Q=100 if original_format == "png" else q["quality"],
                effort=6,
                strip=True,
            )
        case _:
            raise ValueError(f"unsupported format: {q['format']}")


bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

query_schema = Schema(
    {
        "width": And(Use(int), lambda n: n > 0),
        "height": And(Use(int), lambda n: n > 0),
        "quality": And(Use(int), lambda n: 0 < n <= 100),
        "format": And(str, Use(str.lower), lambda s: s in ("jpeg", "png", "webp")),
        Optional("crop"): And(
            str,
            Use(lambda s: s.split(",")),
            Use(lambda l: map(int, l)),
            Use(tuple),
        ),
    }
)


async def scale(request: Request):
    """Provide a scaled and/or cropped image."""

    tenant = request.path_params["tenant"]
    image_uri = request.path_params["image_uri"]
    config: Config = request.app.state.config

    span = Hub.current.scope.span
    if span is not None:
        span.set_tag("tenant", tenant)

    in_q, fwd_q = extract_forwardable_params(dict(request.query_params))
    try:
        q = query_schema.validate(in_q)
    except Exception:
        log.exception(
            "invalid query parameters (scale) for %s: %s",
            request.path_params,
            request.query_params,
        )
        raise HTTPException(400, "invalid set of query parameters (scale)")

    if "crop" not in q:
        q["crop"] = None

    request_url = cache_url(
        config.cache_endpoint(),
        config.app_path_prefixes(),
        "original",
        tenant,
        image_uri,
        fwd_q,
    )

    r = await make_request(request, request_url)
    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(
        bg_pool, functools.partial(blocking_scale, r.content, q)
    )

    return Response(content, headers=output_headers, media_type="image/" + q["format"])
