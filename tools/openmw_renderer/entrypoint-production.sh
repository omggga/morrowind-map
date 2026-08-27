#!/usr/bin/env bash
set -euo pipefail

: "${MWMAP_EXPORT_BATCH_FILE:?MWMAP_EXPORT_BATCH_FILE is required}"
: "${MWMAP_EXPORT_BATCH_CENTER:?MWMAP_EXPORT_BATCH_CENTER is required}"
: "${MWMAP_EXPORT_BATCH_ID:?MWMAP_EXPORT_BATCH_ID is required}"

if [[ ! "${MWMAP_EXPORT_BATCH_ID}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "MWMAP_EXPORT_BATCH_ID contains unsafe characters" >&2
  exit 64
fi

runtime_root="/out/runtime/${MWMAP_EXPORT_BATCH_ID}"
mkdir -p "${runtime_root}" /profile/home /profile/user-data

export HOME=/profile/home
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-llvmpipe}"
export OPENMW_DONT_PRECOMPILE="${OPENMW_DONT_PRECOMPILE:-1}"
export OSG_THREADING="${OSG_THREADING:-SingleThreaded}"
export SDL_AUDIODRIVER=dummy
export MWMAP_RUNTIME_ROOT="${runtime_root}"

cp /opt/openmw/build-manifest.txt "${runtime_root}/openmw-build-manifest.txt"

started_at="${SECONDS}"
status=0
# Keep the shell as PID 1: xvfb-run waits forever when it replaces PID 1.
xvfb-run -a -s "-screen 0 640x480x24 +extension GLX +render -noreset" bash -c '
  glxinfo -B > "${MWMAP_RUNTIME_ROOT}/glxinfo.txt"
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
' || status="$?"
elapsed="$((SECONDS - started_at))"

memory_peak="unavailable"
if [[ -r /sys/fs/cgroup/memory.peak ]]; then
  memory_peak="$(tr -cd '0-9' < /sys/fs/cgroup/memory.peak)"
  memory_peak="${memory_peak:-unavailable}"
fi

memory_tmp="${runtime_root}/.memory.peak.$$"
process_tmp="${runtime_root}/.process.json.$$"
printf '%s\n' "${memory_peak}" > "${memory_tmp}"
printf '{"elapsedSeconds":%d,"exitCode":%d}\n' "${elapsed}" "${status}" > "${process_tmp}"
mv "${memory_tmp}" "${runtime_root}/memory.peak"
mv "${process_tmp}" "${runtime_root}/process.json"

exit "${status}"
