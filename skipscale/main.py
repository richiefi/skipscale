import httpx
import sentry_sdk
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.applications import Starlette
from starlette.routing import Route, Mount

from skipscale.config import Config
from skipscale.original import original
from skipscale.imageinfo import imageinfo
from skipscale.scale import scale
from skipscale.encrypt import encrypt
from skipscale.planner import planner

routes = [
    Route('/original/{tenant}/{image_uri:path}', original),
    Route('/imageinfo/{tenant}/{image_uri:path}', imageinfo),
    Route('/scale/{tenant}/{image_uri:path}', scale),
    Route('/{tenant}/{image_uri:path}', planner),
    Route('/{tenant}/', encrypt, methods=["POST"]),
]

app_config = Config()
final_routes = []
for prefix in app_config.app_path_prefixes():
    final_routes.append(Mount(prefix, routes=routes))

app = Starlette(routes=final_routes)
app.state.config = app_config
app.state.httpx_client = httpx.AsyncClient(http2=True) # default timeout is 5 seconds

if app_config.sentry_dsn():
    sentry_sdk.init(dsn=app_config.sentry_dsn())
    app = SentryAsgiMiddleware(app)
