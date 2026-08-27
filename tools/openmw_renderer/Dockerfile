FROM ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517

ARG DEBIAN_FRONTEND=noninteractive
ARG OPENMW_COMMIT=f4bec41444214a7903bebd178389ca22ca13f646
ARG UBUNTU_SNAPSHOT=20260826T000000Z

LABEL org.opencontainers.image.title="morrowind-map OpenMW exporter spike" \
      org.opencontainers.image.source="https://github.com/omggga/morrowind-map" \
      org.opencontainers.image.revision="${OPENMW_COMMIT}" \
      io.morrowind-map.stage="4.5" \
      io.morrowind-map.base-image="ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517" \
      io.morrowind-map.ubuntu-snapshot="${UBUNTU_SNAPSHOT}"

RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/80-morrowind-map \
    && sed -i 's/^Components: .*/Components: main/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates=20240203 \
    && sed -i 's/^Components: main$/Components: main universe restricted multiverse/' /etc/apt/sources.list.d/ubuntu.sources \
    && sed -i "s|URIs: http://archive.ubuntu.com/ubuntu/|URIs: https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}/|" /etc/apt/sources.list.d/ubuntu.sources \
    && sed -i "s|URIs: http://security.ubuntu.com/ubuntu/|URIs: https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}/|" /etc/apt/sources.list.d/ubuntu.sources \
    && printf 'Package: *\nPin: origin "snapshot.ubuntu.com"\nPin-Priority: 1001\n' > /etc/apt/preferences.d/90-morrowind-map-snapshot \
    && apt-get update \
    && apt-get dist-upgrade -y --no-install-recommends --allow-downgrades \
    && apt-get install -y --no-install-recommends \
        build-essential cmake git ninja-build pkg-config \
        libboost-iostreams-dev libboost-program-options-dev libboost-system-dev \
        libavcodec-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev \
        libbullet-dev libcollada-dom-dev libfreetype-dev libicu-dev libjpeg-dev libluajit-5.1-dev \
        liblz4-dev libopenal-dev libopenscenegraph-dev libpng-dev \
        libsdl2-dev libsqlite3-dev libtinyxml-dev libunshield-dev \
        libyaml-cpp-dev libgl-dev libglu1-mesa-dev \
        libgl1-mesa-dri libglx-mesa0 mesa-utils xauth xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none https://gitlab.com/OpenMW/openmw.git /src/openmw \
    && git -C /src/openmw checkout --detach "${OPENMW_COMMIT}" \
    && test "$(git -C /src/openmw rev-parse HEAD)" = "${OPENMW_COMMIT}"

COPY tools/openmw_renderer/patches/openmw-0.51.0-map-export.patch /tmp/openmw-map-export.patch
RUN git -C /src/openmw apply --check /tmp/openmw-map-export.patch \
    && git -C /src/openmw apply /tmp/openmw-map-export.patch

RUN cmake -S /src/openmw -B /build/openmw -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/openmw \
        -DBUILD_SHARED_LIBS=OFF \
        -DBUILD_OPENMW=ON \
        -DBUILD_LAUNCHER=OFF \
        -DBUILD_WIZARD=OFF \
        -DBUILD_OPENCS=OFF \
        -DBUILD_MWINIIMPORTER=OFF \
        -DBUILD_ESSIMPORTER=OFF \
        -DBUILD_BSATOOL=OFF \
        -DBUILD_ESMTOOL=OFF \
        -DBUILD_NIFTEST=OFF \
        -DBUILD_NAVMESHTOOL=OFF \
        -DBUILD_BULLETOBJECTTOOL=OFF \
        -DBUILD_DOCS=OFF \
        -DBUILD_COMPONENTS_TESTS=OFF \
        -DBUILD_OPENMW_TESTS=OFF \
        -DDEPLOY_QT_TRANSLATIONS=OFF \
        -DUSE_SYSTEM_TINYXML=ON \
        -DOPENMW_USE_SYSTEM_MYGUI=OFF \
        -DOPENMW_USE_SYSTEM_RECASTNAVIGATION=OFF \
    && cmake --build /build/openmw --target openmw --parallel 4 \
    && cmake --install /build/openmw

COPY tools/openmw_renderer/patches/openmw-0.51.0-map-export-once.patch /tmp/openmw-map-export-once.patch
RUN git -C /src/openmw apply --check /tmp/openmw-map-export-once.patch \
    && git -C /src/openmw apply /tmp/openmw-map-export-once.patch \
    && cmake --build /build/openmw --target openmw --parallel 4 \
    && cmake --install /build/openmw

RUN mkdir -p /opt/openmw \
    && { \
        printf 'openmw_commit=%s\n' "$(git -C /src/openmw rev-parse HEAD)"; \
        printf 'compiler=%s\n' "$(c++ --version | head -n 1)"; \
        printf 'cmake=%s\n' "$(cmake --version | head -n 1)"; \
        printf 'packages_begin\n'; \
        dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort; \
        printf 'packages_end\n'; \
      } > /opt/openmw/build-manifest.txt

COPY tools/openmw_renderer/entrypoint.sh /usr/local/bin/morrowind-map-openmw-export
RUN chmod 0755 /usr/local/bin/morrowind-map-openmw-export
ARG RENDERER_FINGERPRINT=unversioned
LABEL io.morrowind-map.renderer-fingerprint="${RENDERER_FINGERPRINT}"

ENTRYPOINT ["/usr/local/bin/morrowind-map-openmw-export"]
