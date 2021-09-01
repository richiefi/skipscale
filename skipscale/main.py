"""Skipscale app setup. To be imported by an ASGI runner."""

import logging
import os

import httpx
import sentry_sdk
import uvicorn.workers

from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, Mount

from skipscale.utils import get_logger, FallbackingAsyncBackend
from skipscale.config import Config
from skipscale.original import original
from skipscale.imageinfo import imageinfo
from skipscale.visionrecognizer import visionrecognizer
from skipscale.scale import scale
from skipscale.encrypt import encrypt
from skipscale.planner import planner

# This doesn't currently (2021/3) work with uvloop, only with the native
# asyncio. Enabling disables uvloop. This should be enabled by default
# if https://github.com/MagicStack/uvloop/issues/406 gets fixed.
USE_HAPPY_EYEBALLS = os.environ.get('SKIPSCALE_HAPPY_EYEBALLS') == '1'


async def healthcheck(_):
    return Response(status_code=200)

# pylint: disable=protected-access
def monkeypatch_pil():
    # Pillow may use a buffer size (default ImageFile.MAXBLOCK == 65536 when writing this) that is too low
    # for some present-day JPEG images. Especially using 4:4:4 chroma subsampling with a JPEG quality
    # less than 95 will end up with Pillow using too small buffers for the output.
    #
    # Increase MAXBLOCK to increase the smallest possible buffer size for saving images in Pillow.
    from PIL import ImageFile
    ImageFile.MAXBLOCK = 1024**3
    # Also try to recover from semi-broken images. This fixes problems with some customers'
    # image servers.
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    # Some combination of library and Pillow versions interprets JPEGs as MPOs.
    # We don't ever expect to see MPO files, so monkeypatch Pillow to disable the detection
    # completely.
    from PIL import JpegImagePlugin
    JpegImagePlugin._getmp = lambda _: None


routes = [
    # Used for original images
    Route('/original/{tenant}/{image_uri:path}', original, methods=['GET', 'OPTIONS']),
    # Used for reverse-proxying non-image assets
    Route('/asset/{tenant}/{image_uri:path}', original, methods=['GET', 'OPTIONS']),

    Route('/imageinfo/{tenant}/{image_uri:path}', imageinfo),
    Route('/visionrecognizer/{tenant}/{image_uri:path}', visionrecognizer),
    Route('/scale/{tenant}/{image_uri:path}', scale),
    Route('/{tenant}/{image_uri:path}', planner),
    Route('/{tenant}/', encrypt, methods=["POST"]),
    Route('/', healthcheck)
]

# Custom logging setup so as not to disturb the ASGI server's logging.
log_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log_handler = logging.StreamHandler()
log_handler.setFormatter(log_fmt)
log = get_logger()
log.addHandler(log_handler)
log.propagate = False
if os.environ.get('SKIPSCALE_DEBUG') == '1':
    log.setLevel(logging.DEBUG)
else:
    log.setLevel(logging.INFO)
log.debug('app starting')

monkeypatch_pil()

app_config = Config()
final_routes = []
for prefix in app_config.app_path_prefixes():
    final_routes.append(Mount(prefix, routes=routes))

app = Starlette(routes=final_routes)
app.state.config = app_config

uvicorn_args = {}
if USE_HAPPY_EYEBALLS:
    log.info('enabling Happy Eyeballs support (disabling uvloop)')
    # FallbackingAsyncBackend doesn't work if loop=uvloop
    uvicorn_args['loop'] = 'asyncio'
    httpcore_backend = FallbackingAsyncBackend() # enables Happy Eyeballs
else:
    # Let uvicorn and httpcore do whatever they do by default
    httpcore_backend = 'auto' # interpreted by httpcore

timeout = httpx.Timeout(
    app_config.origin_request_timeout_seconds(),
    connect=app_config.origin_request_connect_timeout_seconds()
)

limits = httpx.Limits(
    max_keepalive_connections=app_config.origin_request_max_keepalive_connections(),
    max_connections=app_config.origin_request_max_connections()
)

transport = httpx.AsyncHTTPTransport(
    http2=app_config.origin_request_http2(),
    limits=limits,
    local_address=app_config.origin_request_local_address(),
    backend=httpcore_backend
)

app.state.httpx_client = httpx.AsyncClient(timeout=timeout, transport=transport)

if app_config.sentry_dsn():
    if app_config.sentry_traces_sample_rate():
        sentry_sdk.init(dsn=app_config.sentry_dsn(),
                        traces_sample_rate=app_config.sentry_traces_sample_rate())
    else:
        sentry_sdk.init(dsn=app_config.sentry_dsn())
    app.add_middleware(SentryAsgiMiddleware)

# gunicorn doesn't allow passing through all uvicorn parameters, use a custom
# worker class to do it. Specify --worker-class skipscale.main.MyUvicornWorker
# to use this.
# pylint: disable=missing-class-docstring
class MyUvicornWorker(uvicorn.workers.UvicornWorker):
    CONFIG_KWARGS = uvicorn_args
