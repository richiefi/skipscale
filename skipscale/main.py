"""Skipscale app setup. To be imported by an ASGI runner."""

import logging
import os

import httpx
import sentry_sdk

from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, Mount

from skipscale.utils import get_logger
from skipscale.config import Config
from skipscale.original import original
from skipscale.imageinfo import imageinfo
from skipscale.visionrecognizer import visionrecognizer
from skipscale.scale import scale
from skipscale.encrypt import encrypt
from skipscale.planner import planner


async def healthcheck(_):
    return Response(status_code=200)


routes = [
    # Used for original images
    Route("/original/{tenant}/{image_uri:path}", original, methods=["GET", "OPTIONS"]),
    # Used for reverse-proxying non-image assets
    Route("/asset/{tenant}/{image_uri:path}", original, methods=["GET", "OPTIONS"]),
    Route("/imageinfo/{tenant}/{image_uri:path}", imageinfo),
    Route("/visionrecognizer/{tenant}/{image_uri:path}", visionrecognizer),
    Route("/scale/{tenant}/{image_uri:path}", scale),
    Route("/{tenant}/{image_uri:path}", planner),
    Route("/{tenant}/", encrypt, methods=["POST"]),
    Route("/", healthcheck),
]

# Custom logging setup so as not to disturb the ASGI server's logging.
log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log_handler = logging.StreamHandler()
log_handler.setFormatter(log_fmt)
log = get_logger()
log.addHandler(log_handler)
log.propagate = False
if os.environ.get("SKIPSCALE_DEBUG") == "1":
    log.setLevel(logging.DEBUG)
else:
    log.setLevel(logging.INFO)
log.debug("app starting")

app_config = Config()
final_routes = []
for prefix in app_config.app_path_prefixes():
    final_routes.append(Mount(prefix, routes=routes))

app = Starlette(routes=final_routes)
app.state.config = app_config

timeout = httpx.Timeout(
    app_config.origin_request_timeout_seconds(),
    connect=app_config.origin_request_connect_timeout_seconds(),
)

limits = httpx.Limits(
    max_keepalive_connections=app_config.origin_request_max_keepalive_connections(),
    max_connections=app_config.origin_request_max_connections(),
)

transport = httpx.AsyncHTTPTransport(
    http2=app_config.origin_request_http2(),
    limits=limits,
    local_address=app_config.origin_request_local_address(),
)

app.state.httpx_client = httpx.AsyncClient(timeout=timeout, transport=transport)

if app_config.sentry_dsn():
    if app_config.sentry_traces_sample_rate():
        if app_config.sentry_profiles_sample_rate():
            sentry_sdk.init(
                dsn=app_config.sentry_dsn(),
                traces_sample_rate=app_config.sentry_traces_sample_rate(),
                profiles_sample_rate=app_config.sentry_profiles_sample_rate(),
            )
        else:
            sentry_sdk.init(
                dsn=app_config.sentry_dsn(),
                traces_sample_rate=app_config.sentry_traces_sample_rate(),
            )
    else:
        sentry_sdk.init(dsn=app_config.sentry_dsn())
    app.add_middleware(SentryAsgiMiddleware)
