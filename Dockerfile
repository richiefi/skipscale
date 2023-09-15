FROM python:3.10.13-bullseye
ARG CC=cc

ENV WORKER_PROCESSES 16
ENV SKIPSCALE_CONFIG config.toml
ENV BIND_ADDR 127.0.0.1:8000

ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
# Dummy env, increment to force builder to abandon apt cache
ENV APTDATE 20230915

ARG mozjpeg_tag=v4.1.4

RUN apt-get update && apt-get dist-upgrade -y && \
    apt-get install cmake nasm meson libgirepository1.0-dev libfftw3-dev liborc-0.4-dev -y --no-install-recommends && \
    rm -rf /tmp/* && rm -rf /var/cache/apt/archives/*.deb && rm -rf /var/lib/apt/lists/*

RUN pip3 install pipenv

WORKDIR /src/mozjpeg
ADD https://github.com/mozilla/mozjpeg/archive/$mozjpeg_tag.tar.gz ./

# Debian de-priorities /usr/local/lib by default, so libvips attemps to use the system libjpeg even if we've installed mozjpeg
ENV LD_LIBRARY_PATH /usr/local/lib

RUN tar -xzf $mozjpeg_tag.tar.gz && \
    rm $mozjpeg_tag.tar.gz && \
    SRC_DIR=$(ls -t1 -d mozjpeg-* | head -n1) && \
    CC="$CC" cmake -G"Unix Makefiles" -DCMAKE_INSTALL_PREFIX=/usr/local $SRC_DIR && \
    CC="$CC" make install && \
    ldconfig && \
    rm -rf /src/*

WORKDIR /src/libvips
ADD https://github.com/libvips/libvips/releases/download/v8.14.4/vips-8.14.4.tar.xz ./
RUN tar -xJf vips-8.14.4.tar.xz && \
    rm vips-8.14.4.tar.xz && \
    cd vips-8.14.4 && \
    CC="$CC" LDFLAGS="-L/usr/local/lib" CFLAGS="-I/usr/local/include" meson setup build-dir --prefix=/usr/local --buildtype=release && \
    cd build-dir && \
    ninja && \
    ninja install && \
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
