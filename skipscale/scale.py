import asyncio
import concurrent.futures
import functools
from io import BytesIO

from PIL import Image
from schema import Schema, And, Optional, Use
from starlette.exceptions import HTTPException
from starlette.responses import Response, StreamingResponse

from skipscale.exif_transpose import image_transpose_exif
from skipscale.utils import cache_url, cache_headers, make_request

def blocking_scale(content, q):
    i = Image.open(BytesIO(content))
    original_format = i.format
    i = image_transpose_exif(i)
    i = i.resize((q['width'], q['height']), Image.LANCZOS, q['crop'], reducing_gap = 3.0)
    if q['format'] == 'jpeg':
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
    return fp

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

    try:
        q = query_schema.validate(dict(request.query_params))
    except:
        raise HTTPException(400, "invalid set of query parameters")

    if 'crop' not in q:
        q['crop'] = None

    request_url = cache_url(
        request.app.state.config.cache_endpoint(),
        request.app.state.config.app_path_prefixes(),
        "original",
        tenant,
        image_uri
    )

    r = await make_request(request, request_url)
    output_headers = cache_headers(request.app.state.config.cache_control_override(tenant), r)

    if r.status_code == 304:
        return Response(status_code=304, headers=output_headers)
    
    if r.status_code > 399:
        raise HTTPException(r.status_code)

    loop = asyncio.get_running_loop()
    fp = await loop.run_in_executor(bg_pool, functools.partial(blocking_scale, r.content, q))

    return StreamingResponse(fp, headers=output_headers, media_type="image/"+q['format'])
