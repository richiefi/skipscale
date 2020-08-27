import base64
import binascii

from schema import Schema, Use
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
import validators

from skipscale.urlcrypto import encrypt_url

post_schema = Schema({
    'urls': [validators.url],
})

def authenticate(request, tenant):
    if "Authorization" not in request.headers:
        return

    auth = request.headers["Authorization"]
    try:
        scheme, credentials = auth.split()
        if scheme.lower() != 'basic':
            return
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
        body = await request.json()
        urls = post_schema.validate(body)
    except:
        raise HTTPException(400)

    key = request.app.state.config.encryption_key(tenant)
    if not key:
        raise HTTPException(400)

    prefix = request.app.state.config.encryption_url_prefix(tenant) + tenant + '/'
    result = {}
    for url in urls['urls']:
        if url.endswith(".jpg") or url.endswith(".jpeg"):
            extension = ".jpg"
        elif url.endswith(".png"):
            extension = ".png"
        elif url.endswith(".gif"):
            extension = ".gif"
        else:
            extension = ""
        result[url] = prefix + encrypt_url(key, tenant, url) + extension
    
    return JSONResponse({'processedURLs': result})
