import httpx, httpcore
import sentry_sdk
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, Mount

from skipscale.config import Config
from skipscale.original import original
from skipscale.imageinfo import imageinfo
from skipscale.scale import scale
from skipscale.encrypt import encrypt
from skipscale.planner import planner

async def healthcheck(request):
    return Response(status_code=200)

routes = [
    Route('/original/{tenant}/{image_uri:path}', original),
    Route('/imageinfo/{tenant}/{image_uri:path}', imageinfo),
    Route('/scale/{tenant}/{image_uri:path}', scale),
    Route('/{tenant}/{image_uri:path}', planner),
    Route('/{tenant}/', encrypt, methods=["POST"]),
    Route('/', healthcheck)
]

app_config = Config()
final_routes = []
for prefix in app_config.app_path_prefixes():
    final_routes.append(Mount(prefix, routes=routes))

app = Starlette(routes=final_routes)
app.state.config = app_config

pool = httpcore.AsyncConnectionPool(http2=app_config.origin_request_http2(),
    max_keepalive_connections=app_config.origin_request_max_keepalive_connections(),
    max_connections=app_config.origin_request_max_connections(),
    local_address=app_config.origin_request_local_address())
timeout = httpx.Timeout(app_config.origin_request_timeout_seconds(), connect=app_config.origin_request_connect_timeout_seconds())
app.state.httpx_client = httpx.AsyncClient(timeout=timeout, transport=pool)

if app_config.sentry_dsn():
    if app_config.sentry_traces_sample_rate():
        sentry_sdk.init(dsn=app_config.sentry_dsn(), traces_sample_rate=app_config.sentry_traces_sample_rate())
    else:
        sentry_sdk.init(dsn=app_config.sentry_dsn())
    app = SentryAsgiMiddleware(app)
