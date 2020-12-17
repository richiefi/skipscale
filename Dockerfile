FROM ubuntu:rolling
ARG CC=cc

ENV WORKER_PROCESSES 16
ENV SKIPSCALE_CONFIG config.toml
ENV BIND_ADDR 127.0.0.1:8000

ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1

ARG mozjpeg_tag=v4.0.0

RUN apt-get update && \
    apt-get install cmake libtool nasm make pkg-config curl python3.8-dev python3.8-distutils libffi-dev libpng-dev libwebp-dev zlib1g-dev ca-certificates -y --no-install-recommends && \
    rm -rf /tmp/* && rm -rf /var/cache/apt/archives/*.deb && rm -rf /var/lib/apt/lists/*

RUN curl --silent https://bootstrap.pypa.io/get-pip.py | python3.8

# Backwards compatility.
RUN rm -fr /usr/bin/python3 && ln /usr/bin/python3.8 /usr/bin/python3

RUN pip3 install pipenv

WORKDIR /src/mozjpeg
ADD https://github.com/mozilla/mozjpeg/archive/$mozjpeg_tag.tar.gz ./

RUN tar -xzf $mozjpeg_tag.tar.gz && \
    rm $mozjpeg_tag.tar.gz && \
    SRC_DIR=$(ls -t1 -d mozjpeg-* | head -n1) && \
    CC="$CC" cmake -G"Unix Makefiles" -DCMAKE_INSTALL_PREFIX=/usr/local $SRC_DIR && \
    CC="$CC" make install && \
    ldconfig && \
    rm -rf /src/*

# -- Install Application into container:
RUN set -ex && mkdir /app

WORKDIR /app

# -- Adding Pipfiles
COPY Pipfile .
COPY Pipfile.lock .

# -- Install dependencies:
RUN set -ex && CC="$CC" LDFLAGS="-L/usr/local/lib" CFLAGS="-I/usr/local/include" pipenv install --deploy --system

# -- Add the application
COPY . .

EXPOSE 8000
CMD exec gunicorn skipscale.main:app --bind $BIND_ADDR --workers $WORKER_PROCESSES --worker-class uvicorn.workers.UvicornWorker
