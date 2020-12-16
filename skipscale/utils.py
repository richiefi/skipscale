"""Miscellaneous utility functions."""

import logging
from urllib.parse import urljoin, urlencode
from typing import Optional, Union, Dict

from httpx import RequestError, AsyncClient
from starlette.exceptions import HTTPException

def get_logger(*components) -> logging.Logger:
    """Get a logger under the app's hierarchy."""

    name = '.'.join(['skipscale'] + list(components))
    return logging.getLogger(name)

def cache_url(cache_endpoint, app_path_prefixes, url_type, tenant, image_uri, params=None) -> str:
    app_prefix = urljoin(cache_endpoint, app_path_prefixes[0])
    url = urljoin(app_prefix, url_type + '/' + tenant + '/' + image_uri)
    if params:
        url = urljoin(url, '?' + urlencode(params, safe=','))
    return url

async def make_request(incoming_request, outgoing_request_url,
                       stream=False, method='GET',
                       proxy: Optional[str] = None):
    log = get_logger('utils', 'make_request')

    outgoing_request_headers = {}
    def fwd_header(name, do_log=False) -> None:
        if name in incoming_request.headers:
            outgoing_request_headers[name] = incoming_request.headers[name]
            if do_log:
                log.debug('forwarding downstream %s: %s', name, outgoing_request_headers[name])

    fwd_header('if-modified-since')
    fwd_header('if-none-match')
    fwd_header('origin', do_log=True)
    fwd_header('access-control-request-method')
    fwd_header('access-control-request-headers')

    close_client = False
    client = incoming_request.app.state.httpx_client

    # httpx proxy settings are per-client, if one is set we need to create a new one
    # instead of using the global instance. This assumes that proxy usage is limited
    # to test/QA feeds.
    if proxy:
        close_client = True
        client = AsyncClient(timeout=client.timeout, proxies=proxy)
        log.debug('fetching %s through proxy', outgoing_request_url)

    req = client.build_request(method, outgoing_request_url, headers=outgoing_request_headers)
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
                  allow_cors: Union[str, dict, bool] = False):
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
        elif isinstance(allow_cors, dict):
            output_headers.update(allow_cors)
        else:
            output_headers['access-control-allow-origin'] = '*'
        output_headers['vary'] = 'origin'
    return output_headers

def should_allow_cors(force_flag: bool, upstream_response) -> Union[dict, bool]:
    log = get_logger('utils', 'should_allow_cors')

    # If force is set in configuration, always return ACAO=*
    if force_flag:
        log.debug('forcing ACAO')
        return True

    # Check if upstream returned ACAO and pass it on if it did
    if upstream_response is not None and 'access-control-allow-origin' in upstream_response.headers:
        acao = upstream_response.headers['access-control-allow-origin']
        addl_headers: Dict[str, str] = {
            'access-control-allow-origin': acao
        }

        if 'access-control-allow-method' in upstream_response.headers:
            addl_headers['access-control-allow-method'] = \
                upstream_response.headers['access-control-allow-method']
        if 'access-control-allow-headers' in upstream_response.headers:
            addl_headers['access-control-allow-headers'] = \
                upstream_response.headers['access-control-allow-headers']

        log.debug('forwarding upstream ACAO: %s', acao)
        return acao

    return False
