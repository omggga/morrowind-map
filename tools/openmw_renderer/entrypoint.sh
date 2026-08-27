#!/usr/bin/env bash
set -euo pipefail

: "${MWMAP_EXPORT_CELL:?MWMAP_EXPORT_CELL is required}"
: "${MWMAP_EXPORT_PATH:?MWMAP_EXPORT_PATH is required}"

mkdir -p /out/runtime /profile/home /profile/user-data

export HOME=/profile/home
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-llvmpipe}"
export OPENMW_DONT_PRECOMPILE="${OPENMW_DONT_PRECOMPILE:-1}"
export OSG_THREADING="${OSG_THREADING:-SingleThreaded}"
export SDL_AUDIODRIVER=dummy

cp /opt/openmw/build-manifest.txt /out/runtime/openmw-build-manifest.txt

# Keep the entrypoint shell as PID 1. Xvfb only signals readiness when its
# parent PID is greater than 1, so exec'ing xvfb-run here deadlocks in Docker.
xvfb-run -a -s "-screen 0 640x480x24 +extension GLX +render -noreset" bash -c '
  glxinfo -B > /out/runtime/glxinfo.txt
  exec /opt/openmw/bin/openmw \
    --config=/profile/config \
    --user-data=/profile/user-data \
    --resources=/opt/openmw/share/games/openmw/resources \
    --skip-menu \
    --no-sound \
    --script-console \
    --script-run=/profile/commands.txt \
    --random-seed=1 \
    --no-grab
'
