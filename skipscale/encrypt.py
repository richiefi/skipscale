import base64
import binascii
import logging

from schema import Schema, Optional, SchemaError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
import validators

from skipscale.urlcrypto import encrypt_url
from skipscale.config import Config

log = logging.getLogger(__name__)
post_schema = Schema({
    Optional('urls'): [validators.url],
    Optional('asset_urls'): [validators.url]
})

def authenticate(request, tenant) -> bool:
    if "Authorization" not in request.headers:
        return False

    auth = request.headers["Authorization"]
    try:
        scheme, credentials = auth.split()
        if scheme.lower() != 'basic':
            return False
        decoded = base64.b64decode(credentials).decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(401)

    username, _, password = decoded.partition(":")
    valid_username, valid_password = request.app.state.config.encryption_credentials(tenant)
    if username == valid_username and password == valid_password:
        return True
    return False

async def encrypt(request):
    tenant = request.path_params['tenant']
    if not authenticate(request, tenant):
        raise HTTPException(401)
    try:
        raw_body = await request.json()
        body = post_schema.validate(raw_body)
    except SchemaError as exc:
        log.warning('encrypt request validation failed: %s', exc)
        raise HTTPException(400, detail='Validation failed')
    except Exception:
        log.exception('encrypt request parsing failed')
        raise HTTPException(400, detail='Parsing failed')

    key = request.app.state.config.encryption_key(tenant)
    if not key:
        raise HTTPException(400, detail='Missing configuration')

    config: Config = request.app.state.config
    image_prefix = config.encryption_url_prefix(tenant) + tenant + '/'
    asset_prefix = config.encryption_asset_url_prefix(tenant) + 'asset/' + tenant + '/'
    result = {}

    def array_to_result(prefix, orig_urls) -> None:
        src_urls: list
        if not isinstance(orig_urls, list):
            src_urls = []
        else:
            src_urls = orig_urls

        for url in src_urls:
            if url.endswith(".jpg") or url.endswith(".jpeg"):
                extension = ".jpg"
            elif url.endswith(".png"):
                extension = ".png"
            elif url.endswith(".gif"):
                extension = ".gif"
            else:
                extension = ""
            result[url] = prefix + encrypt_url(key, tenant, url) + extension

    array_to_result(asset_prefix, body.get('asset_urls', []))
    array_to_result(image_prefix, body.get('urls', []))

    return JSONResponse({'processedURLs': result})
