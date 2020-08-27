from urllib.parse import urljoin, urlencode

from httpx import RequestError
from starlette.exceptions import HTTPException

def cache_url(cache_endpoint, app_path_prefixes, url_type, tenant, image_uri, params=None) -> str:
    app_prefix = urljoin(cache_endpoint, app_path_prefixes[0])
    url = urljoin(app_prefix, url_type + '/' + tenant + '/' + image_uri)
    if params:
        url = urljoin(url, '?' + urlencode(params, safe=','))
    return url

async def make_request(incoming_request, outgoing_request_url, stream=False):
    outgoing_request_headers = {}
    if 'if-modified-since' in incoming_request.headers:
        outgoing_request_headers['if-modified-since'] = incoming_request.headers['if-modified-since']
    if 'if-none-match' in incoming_request.headers:
        outgoing_request_headers['if-none-match'] = incoming_request.headers['if-none-match']
    req = incoming_request.app.state.httpx_client.build_request("GET", outgoing_request_url, headers=outgoing_request_headers)
    try:
        r = await incoming_request.app.state.httpx_client.send(req, stream=stream)
    except RequestError:
        raise HTTPException(502)
    if r.is_error:
        raise HTTPException(r.status_code)
    return r

def cache_headers(cache_control_override, received_response):
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
    return output_headers
