import logging
from urllib.parse import urljoin, urlencode
from typing import Optional, Union

from httpx import RequestError, AsyncClient
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)


def cache_url(cache_endpoint, app_path_prefixes, url_type, tenant, image_uri, params=None) -> str:
    app_prefix = urljoin(cache_endpoint, app_path_prefixes[0])
    url = urljoin(app_prefix, url_type + '/' + tenant + '/' + image_uri)
    if params:
        url = urljoin(url, '?' + urlencode(params, safe=','))
    return url

async def make_request(incoming_request, outgoing_request_url,
                       stream=False,
                       proxy: Optional[str] = None):
    outgoing_request_headers = {}
    if 'if-modified-since' in incoming_request.headers:
        outgoing_request_headers['if-modified-since'] = incoming_request.headers['if-modified-since']
    if 'if-none-match' in incoming_request.headers:
        outgoing_request_headers['if-none-match'] = incoming_request.headers['if-none-match']

    close_client = False
    client = incoming_request.app.state.httpx_client

    # httpx proxy settings are per-client, if one is set we need to create a new one
    # instead of using the global instance. This assumes that proxy usage is limited
    # to test/QA feeds.
    if proxy:
        close_client = True
        client = AsyncClient(timeout=client.timeout, proxies=proxy)
        log.debug('fetching %s through proxy', outgoing_request_url)

    req = client.build_request("GET", outgoing_request_url, headers=outgoing_request_headers)
    try:
        r = await client.send(req, stream=stream)
    except RequestError:
        raise HTTPException(502)
    finally:
        if close_client:
            await client.aclose()

    if r.is_error:
        raise HTTPException(r.status_code)

    return r

def cache_headers(cache_control_override, received_response,
                  allow_cors: Union[str, bool] = False):
    output_headers = {}
    if 'last-modified' in received_response.headers:
        output_headers['last-modified'] = received_response.headers['last-modified']
    if 'etag' in received_response.headers:
        output_headers['etag'] = received_response.headers['etag']
    if cache_control_override:
        output_headers['cache-control'] = cache_control_override
    else:
        if 'cache-control' in received_response.headers:
            output_headers['cache-control'] = received_response.headers['cache-control']
        if 'expires' in received_response.headers:
            output_headers['expires'] = received_response.headers['expires']
        if 'pragma' in received_response.headers:
            output_headers['pragma'] = received_response.headers['pragma']
    if allow_cors:
        if isinstance(allow_cors, str):
            output_headers['access-control-allow-origin'] = allow_cors
        else:
            output_headers['access-control-allow-origin'] = '*'
        output_headers['vary'] = 'origin'
    return output_headers

def should_allow_cors(request, force_flag: bool):
    # TODO: ACAO is forced unconditionally until Varnish issues can be resolved
    #if 'origin' in request.headers and force_flag:
    if force_flag:
        return True

    return False
