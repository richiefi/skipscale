import asyncio
import base64
import binascii
from typing import Any
from urllib.parse import urljoin

from httpx import AsyncClient
from schema import Schema, Optional, SchemaError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
import validators

from skipscale.urlcrypto import encrypt_url
from skipscale.utils import get_logger
from skipscale.config import Config

log = get_logger(__name__)

post_schema = Schema(
    {
        Optional("urls"): [validators.url],
        Optional("asset_urls"): [validators.url],
        Optional("include_thumbnail_crop", default=False): bool,
    }
)


def authenticate(request, tenant) -> bool:
    if "Authorization" not in request.headers:
        return False

    auth = request.headers["Authorization"]
    try:
        scheme, credentials = auth.split()
        if scheme.lower() != "basic":
            return False
        decoded = base64.b64decode(credentials).decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(401)

    username, _, password = decoded.partition(":")
    valid_username, valid_password = request.app.state.config.encryption_credentials(
        tenant
    )
    if username == valid_username and password == valid_password:
        return True
    return False


async def encrypt(request: Request):
    tenant = request.path_params["tenant"]
    if not authenticate(request, tenant):
        raise HTTPException(401)
    try:
        raw_body = await request.json()
        body = post_schema.validate(raw_body)
    except SchemaError as exc:
        log.warning("encrypt request validation failed: %s", exc)
        raise HTTPException(400, detail="Validation failed")
    except Exception:
        log.exception("encrypt request parsing failed")
        raise HTTPException(400, detail="Parsing failed")

    key = request.app.state.config.encryption_key(tenant)
    if not key:
        raise HTTPException(400, detail="Missing configuration")

    config: Config = request.app.state.config
    visionrecognizer_prefix = urljoin(
        config.cache_endpoint(),
        config.app_path_prefixes()[0] + "visionrecognizer/" + tenant + "/",
    )
    image_prefix = config.encryption_url_prefix(tenant) + tenant + "/"
    asset_url_prefix = config.encryption_asset_url_prefix(tenant)
    if asset_url_prefix:
        asset_prefix = asset_url_prefix + "asset/" + tenant + "/"
    else:
        asset_prefix = None

    # The result is a dict with each key being the source URL and the value being either an encrypted URL,
    # or, if the request asked for a thumbnail crop, a dict with the thumbnail URL and the crop parameters.
    result: dict[str, Any] = {}

    def array_to_result(
        result: dict[str, Any], orig_urls: list[str], prefix: str = ""
    ) -> None:
        for url in orig_urls:
            if url.endswith(".jpg") or url.endswith(".jpeg"):
                extension = ".jpg"
            elif url.endswith(".png"):
                extension = ".png"
            elif url.endswith(".gif"):
                extension = ".gif"
            else:
                extension = ""
            result[url] = prefix + encrypt_url(key, tenant, url) + extension

    async def visionrecognizer_call(src_url, encrypted_url):
        visionrecognizer_url = visionrecognizer_prefix + encrypted_url
        client: AsyncClient = request.app.state.httpx_client
        req = client.build_request("GET", visionrecognizer_url)
        try:
            r = await client.send(req)
            result = r.json()
            thumbnail_crop = {
                "center_x": result["centerPoint"]["x"],
                "center_y": 1.0
                - result["centerPoint"]["y"],  # visionrecognizer has a flipped y-axis
            }
            image_properties = {
                "width": result["imageSize"]["w"],
                "height": result["imageSize"]["h"],
            }
        except Exception:
            return {"src_url": src_url, "encrypted_url": encrypted_url}

        return {
            "src_url": src_url,
            "encrypted_url": encrypted_url,
            "thumbnail_crop": thumbnail_crop,
            "properties": image_properties,
        }

    if body.get("include_thumbnail_crop"):
        image_encrypt_result: dict[str, str] = {}
        array_to_result(image_encrypt_result, body.get("urls", []))
        visionrecognizer_calls = []
        for src_url, encrypted_url in image_encrypt_result.items():
            visionrecognizer_calls.append(visionrecognizer_call(src_url, encrypted_url))
        for visionrecognizer_result in await asyncio.gather(*visionrecognizer_calls):
            img_result: dict[str, str]
            if "thumbnail_crop" in visionrecognizer_result:
                img_result = {
                    "encrypted_url": image_prefix
                    + visionrecognizer_result["encrypted_url"],
                    "thumbnail_crop": visionrecognizer_result["thumbnail_crop"],
                    "properties": visionrecognizer_result["properties"],
                }
            else:
                img_result = {
                    "encrypted_url": image_prefix
                    + visionrecognizer_result["encrypted_url"]
                }
            result[visionrecognizer_result["src_url"]] = img_result
    else:
        array_to_result(result, body.get("urls", []), image_prefix)

    array_to_result(result, body.get("asset_urls", []), asset_prefix)

    return JSONResponse({"processedURLs": result})
