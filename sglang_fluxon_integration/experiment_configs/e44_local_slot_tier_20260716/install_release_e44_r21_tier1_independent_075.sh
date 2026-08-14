#!/usr/bin/env bash
set -euo pipefail

role="${1:?missing install role: gpu or cpu}"
wheel="${2:?missing unified Fluxon wheel path}"
expected_pyo3_sha256="${3:?missing expected fluxon_pyo3 sha256}"

test -f "$wheel"

case "$role" in
  gpu)
    python="${PYTHON3_10:-$(command -v python3.10 || true)}"
    if [ -z "$python" ]; then
      python=/usr/bin/python3.10
    fi
    venv=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    python_version=3.10
    dependency_site=
    ;;
  cpu)
    python="${PYTHON3_12:-$(command -v python3.12 || true)}"
    if [ -z "$python" ]; then
      python=/usr/bin/python3.12
    fi
    venv=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    python_version=3.12
    dependency_site=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-wt-cpu-only-20260710/lib/python3.12/site-packages
    ;;
  *)
    echo "unsupported install role: $role" >&2
    exit 2
    ;;
esac

base_site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages
site="$venv/lib/python${python_version}/site-packages"

if [ ! -e "$venv" ]; then
  "$python" -m venv --system-site-packages "$venv"
fi

test -x "$venv/bin/python"
test "$("$venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "$python_version"
mkdir -p "$site"
printf '%s\n' "$base_site" > "$site/sglang_l13_base_site.pth"
if [ -n "$dependency_site" ]; then
  printf '%s\n' "$dependency_site" > "$site/fluxon_cpu_dependency_site.pth"
fi

"$venv/bin/python" -m pip install --no-index --no-deps --force-reinstall "$wheel"

pyo3="$site/fluxon_pyo3/fluxon_pyo3.abi3.so"
libs="$site/fluxon_pyo3.libs"
test "$(sha256sum "$pyo3" | awk '{print $1}')" = "$expected_pyo3_sha256"
test "$(sha256sum "$libs/libfluxon_commu_core.so" | awk '{print $1}')" = bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503
test "$(sha256sum "$libs/libfluxon_rdma_probe.so" | awk '{print $1}')" = e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883

LD_LIBRARY_PATH="$site/fluxon_pyo3:$libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu" \
  "$venv/bin/python" - "$venv" <<'PY'
from pathlib import Path
import sys

import fluxon_py
import fluxon_pyo3

venv = str(Path(sys.argv[1]).resolve()) + "/"
for module in (fluxon_py, fluxon_pyo3):
    path = str(Path(module.__file__).resolve())
    if not path.startswith(venv):
        raise SystemExit(f"{module.__name__} imported outside versioned venv: {path}")
    print(module.__name__, path)
PY

sha256sum "$wheel" "$pyo3" "$libs/libfluxon_commu_core.so" "$libs/libfluxon_rdma_probe.so"
