from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse

from skipscale.urlcrypto import decrypt_url
from skipscale.utils import cache_headers, make_request

async def original(request):
    """Return an image from the origin."""

    tenant = request.path_params['tenant']
    image_uri = request.path_params['image_uri']

    origin = request.app.state.config.origin(tenant)
    if origin:
        request_url = origin + image_uri
    else:
        # If no origin is specified for the tenant, we expect encrypted urls.
        key = request.app.state.config.encryption_key(tenant)
        try:
            request_url = decrypt_url(key, tenant, image_uri.split('.')[0]) # omit file extension from encrypted url
        except:
            raise HTTPException(400)

    r = await make_request(request, request_url, stream=True)
    output_headers = cache_headers(request.app.state.config.cache_control_override(tenant), r)
    if 'content-type' in r.headers:
        output_headers['content-type'] = r.headers['content-type']
    if 'content-length' in r.headers:
        output_headers['content-length'] = r.headers['content-length']
    return StreamingResponse(r.aiter_bytes(), status_code=r.status_code, headers=output_headers, background=BackgroundTask(r.aclose))
