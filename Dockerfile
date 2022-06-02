FROM python:3.10.4-bullseye
ARG CC=cc

ENV WORKER_PROCESSES 16
ENV SKIPSCALE_CONFIG config.toml
ENV BIND_ADDR 127.0.0.1:8000

ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
# Dummy env, increment to force builder to abandon apt cache
ENV APTDATE 20220602

ARG mozjpeg_tag=v4.0.3

RUN apt-get update && apt-get upgrade -y && \
    apt-get install cmake nasm -y --no-install-recommends && \
    rm -rf /tmp/* && rm -rf /var/cache/apt/archives/*.deb && rm -rf /var/lib/apt/lists/*

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
