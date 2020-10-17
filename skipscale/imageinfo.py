from io import BytesIO

from PIL import Image
from starlette.responses import Response, JSONResponse

from skipscale.exif_transpose import image_transpose_exif
from skipscale.utils import cache_url, cache_headers, make_request

async def imageinfo(request):
    """Return image dimensions, format and byte size."""

    tenant = request.path_params['tenant']
    image_uri = request.path_params['image_uri']

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
    
    i = Image.open(BytesIO(r.content))
    original_format = i.format
    i = image_transpose_exif(i)
    return JSONResponse({'width': i.width, 'height': i.height, 'format': original_format.lower(), 'bytes': len(r.content)}, headers=output_headers)
