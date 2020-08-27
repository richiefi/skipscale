# skipscale

`skipscale` is the third generation image scaler at Richie. It performs recursive HTTP requests on its own endpoints to perform the individual steps of a scaling operation. When deployed together with a caching web proxy such as Varnish, these intermediate steps can be cached to maximize throughput and minimize requests to the image origin. 

Features:

* Multi-tenant origin configuration
* Encrypted image URLs to obscure the origin
* Crop to a specified bounding box or exact dimensions
* Allow the focal point of a crop to be specified
* Use high quality Lanczos scaling
* Output jpeg (using mozjpeg), png, webp

## Request flow

When a request for an image is received, the first step is to transform it to the canonical request, i.e. the request that exactly describes the image we will ultimately respond with. This is determined by the request path and query parameters, but also by the features of the original image: since skipscale never upscales images, and since it maintains image aspect ratio when scaling to a bounding box, the output dimensions are determined in part by the original dimensions of the image.

So, as a first step, we fetch the original image dimensions from the skipscale `imageinfo` endpoint:

`GET /imageinfo/<tenant>/<encrypted origin url>`

The imageinfo endpoint, in turn, requests the original image from the `original` endpoint that decrypts the origin url:

`GET /original/<tenant>/<encrypted origin url>`

Finally, when these recursive requests have returned and the canonical request has been computed, skipscale responds with a redirect to the canonical request URL:

```
HTTP/1.1 307 Moved Temporarily
Location: /scale/<tenant>/<encrypted origin url>?width=<…>&height=<…>&…
```

This redirect is not intended to be served to the client, but instead captured and flattened by the caching proxy skipscale has been deployed with. The example Varnish configuration in `varnish-example.vcl` accomplishes this.

## Supported scaling parameters

* `width`: Optional integer. Required when cropping. If not provided, the width of the returned image is unconstrained.
* `height`: Optional integer. Required when cropping. If not provided, the height of the returned image is unconstrained.
* `dpr`: Display pixel/point ratio. Optional integer, defaults to 1. If set, `width` and `height` are multiplied by this value.
* `quality`: Optional integer between 1 and 100. Default quality is 85; this can be overridden in the config file on a per-tenant basis. Applies to JPEG and lossy WebP files.
* `mode`: Either `fit`, `crop` or `stretch`. Optional, defaults to `fit`. Setting this to `crop` equals setting both `center-x` and `center-y` to 0.5.
* `format`: Either `jpeg`, `png` or `webp`. Optional, defaults to the format of the original image.
* `center-x`: Focal point of the crop. Optional, a floating point number between 0.0 and 1.0. If set, `center-y` is also required. Implies `crop` mode.
* `center-y`: Focal point of the crop. Optional, a floating point number between 0.0 and 1.0. If set, `center-x` is also required. Implies `crop` mode.

## Configuration file

Skipscale expects to find a configuration file named `config.toml` in the current directory. An alternate path may be provided in the `SKIPSCALE_CONFIG` environment variable. See `config.example.toml` for the available options. You should also override the `WORKER_PROCESSES` environment variable (defaults to 16); a good starting point is the number of CPU cores on your system.

## Deployment

Skipscale is intended to be deployed using Docker; the main branch of this repository is automatically built and deployed as the `richiefi/skipscale` image. You can provide a configuration file by building a customized version of the image or by attaching a volume to the container. Specify the path using the `SKIPSCALE_CONFIG` environment variable. For performance, host networking is recommended. Set the bind address using the `BIND_ADDRESS` environment variable.

## macOS dependencies (during development)

```
brew install zlib mozjpeg webp
LDFLAGS="-L/usr/local/opt/mozjpeg/lib -L/usr/local/opt/zlib/lib" CFLAGS="-I/usr/local/opt/mozjpeg/include -I/usr/local/opt/zlib/include" pipenv install
```
