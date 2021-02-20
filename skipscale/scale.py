import asyncio
import concurrent.futures
import functools
from io import BytesIO

from PIL import Image, ImageFile
from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.responses import Response, StreamingResponse

from skipscale.exif_transpose import image_transpose_exif
from skipscale.utils import cache_url, cache_headers_with_config, make_request, \
    get_logger, extract_forwardable_params
from skipscale.config import Config

from sentry_sdk import Hub

log = get_logger(__name__)

ImageFile.LOAD_TRUNCATED_IMAGES = True

def jpegable_image(img: Image) -> Image:
    if img.mode in ('L', 'RGB'):
        return img

    if img.mode == '1':
        return img.convert('L')

    # If not a color image with an alpha channel, convert directly to RGB
    if img.mode != 'RGBA':
        return img.convert('RGB')

    # Image with alpha, composite on white background
    background = Image.new('RGBA', img.size, (255, 255, 255))
    return Image.alpha_composite(background, img).convert('RGB')


def blocking_scale(content, q):
    i = Image.open(BytesIO(content))
    original_format = i.format
    i = image_transpose_exif(i)
    i = i.resize((q['width'], q['height']), Image.LANCZOS, q['crop'], reducing_gap = 3.0)
    if q['format'] == 'jpeg':
        i = jpegable_image(i)
        params = {'format': 'JPEG', 'quality': q['quality'], 'optimize': True, 'progressive': True}
        if q['quality'] >= 90:
            params['subsampling'] = '4:4:4'
    elif q['format'] == 'png':
        params = {'format': 'PNG', 'optimize': True}
    elif q['format'] == 'webp':
        if original_format == 'PNG':
            params = {'format': 'WEBP', 'lossless': True, 'quality': 100}
        else:
            params = {'format': 'WEBP', 'quality': q['quality'], 'method': 6}
    fp = BytesIO()
    i.save(fp, **params)
    fp.seek(0)
    return fp.read()


bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

query_schema = Schema({
    'width': And(Use(int), lambda n: n > 0),
    'height': And(Use(int), lambda n: n > 0),
    'quality': And(Use(int), lambda n: 0 < n <= 100),
    'format': And(str, Use(str.lower), lambda s: s in ('jpeg', 'png', 'webp')),
    Optional('crop'): And(str, Use(lambda s: s.split(',')), Use(lambda l: map(int, l)), Use(lambda l: tuple(l))),
})

async def scale(request):
    """Provide a scaled and/or cropped image."""

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
        log.exception('invalid query parameters (scale) for %s: %s', request.path_params,
                      request.query_params)
        raise HTTPException(400, "invalid set of query parameters (scale)")

    if 'crop' not in q:
        q['crop'] = None

    request_url = cache_url(
        config.cache_endpoint(),
        config.app_path_prefixes(),
        "original",
        tenant,
        image_uri,
        fwd_q
    )

    r = await make_request(request, request_url)
    output_headers = cache_headers_with_config(config, tenant, r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)

    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(bg_pool, functools.partial(blocking_scale, r.content, q))

    return Response(content, headers=output_headers, media_type="image/"+q['format'])
