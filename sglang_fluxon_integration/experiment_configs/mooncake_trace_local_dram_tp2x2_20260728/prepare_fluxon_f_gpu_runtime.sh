#!/usr/bin/env bash
set -euo pipefail

runtime_root="${1:?usage: $0 <runtime-root> <sealed-deployment-dir>}"
deployment_dir="${2:?usage: $0 <runtime-root> <sealed-deployment-dir>}"

case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "runtime root must be a run-scoped /tmp/fluxon_mooncake_f_* path" >&2; exit 2 ;;
esac

release="${FLUXON_F_GPU_RELEASE:-/public/mjq/sglang_fluxon/releases/fluxon_e44_r96_ssd_early_only_gpu_20260728}"
base_venv="${FLUXON_F_BASE_VENV:-/public/mjq/.venv_sglang_fluxon}"
distro_wheel="${FLUXON_F_DISTRO_WHEEL:-/public/mjq/mooncake_m1/deployments/vllm_lmcache_e_20260729_0135_ee17e5d9/wheels/distro-1.9.0-py3-none-any.whl}"
cuda_toolkit_root="${FLUXON_F_CUDA_TOOLKIT_ROOT:-/public/zsh/miniconda3}"
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl
venv="$runtime_root/venv"
cuda_home="$runtime_root/cuda"
src_root="$runtime_root/fluxon_py_src"
gpu_root="$runtime_root/fluxon_f1"
derived_launcher="$gpu_root/start_gpu_stack_owner_tp2x2_f.sh"
derive_manifest="$runtime_root/evidence/launcher_derive.json"
metrics_compat_manifest="$runtime_root/evidence/storage_metrics_compat.json"
kernel_loader_patch_manifest="$runtime_root/evidence/kernel_loader_patch.json"
gdr_off_patch_manifest="$runtime_root/evidence/gdr_off_patch.json"
radix_kernel_loaded="$runtime_root/evidence/unified_radix_cache_kernel_loaded.py"

expected_release_launcher=a3f949e8cc2fcf3efa668941813874f3e6d3e572f106f38d58f5256f20e7f5e5
expected_distro=7bffd925d65168f85027d8da9af6bddab658135b840670a223589bc0c8ef02b2
expected_memory_pool=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
expected_radix_source=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
expected_radix=ba9bea7c8e9b1d645069e56eaff6c7ea0c326bb3956b2bfe06365dccef3cbb07
expected_adapter_source=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
expected_adapter_compat=b1547a8226940bc2f20ddc5567c2ae5be25a967f5eb803545a9dbf70c06d10b6
expected_scheduler=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
expected_kernel_library=c51270e0209cef87c0399d55459b7a30e93ce2f7cc769cdb11085134d83602fc
expected_kernel_loader=b6fcc30d1a3934161bc254a2f07529b6e047791796e18dd9e2b78bc21c259f35
expected_kernel_patcher=11e14c5582591d7fc959e827542b48fd633a72931b801a212561d7ba0aa3133b
expected_gdr_off_patcher=2364a802e8666960926b4a0c64b74d2aba2f74a0917be6b5cfd377ec04ae83eb
expected_pyo3="${FLUXON_F_EXPECTED_PYO3_SHA256:-9ec5a8797c786df4a8c2b43eb43893e78f780caa7de3c5f75e330ddc77392093}"
expected_core="${FLUXON_F_EXPECTED_GPU_CORE_SHA256:-e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c}"
expected_probe="${FLUXON_F_EXPECTED_RDMA_PROBE_SHA256:-e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883}"

test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs
test -x "$base_venv/bin/python"
test -x "$base_venv/bin/ninja"
test -f "$release/fluxon_release.sha256"
test -f "$release/$wheel_name"
test -f "$release/pylib_src.tar.gz"
test -f "$distro_wheel"
test -x "$cuda_toolkit_root/bin/nvcc"
test -x "$cuda_toolkit_root/nvvm/bin/cicc"
test -f "$cuda_toolkit_root/targets/x86_64-linux/include/cuda.h"
test -f "$cuda_toolkit_root/targets/x86_64-linux/lib/libcudart.so"
test -f "$deployment_dir/derive_fluxon_f_launcher.py"
test -f "$deployment_dir/patch_fluxon_f_storage_metrics_compat.py"
test -f "$deployment_dir/patch_fluxon_f_kernel_loader.py"
test -f "$deployment_dir/patch_fluxon_f_gdr_off.py"
test -f "$deployment_dir/fluxon_sgl_kernel_loader.py"
test -f "$deployment_dir/fluxon_sgl_kernel_ops_cuda13.so"
test -f "$deployment_dir/fluxon_wait_ready.sh"
test -f "$deployment_dir/patches/memory_pool_host_fluxon_metadata_only.py"
test -f "$deployment_dir/patches/unified_radix_cache_e44_r61_tp_execute_commit.py"
test -f "$deployment_dir/patches/hicache_fluxon_e44_r54_prefetch_timeline_observe.py"
test -f "$deployment_dir/patches/scheduler_e44_r54_prefetch_timeline_observe.py"

test "$(sha256sum "$release/start_gpu_stack_owner_numa1_ssd.sh" | awk '{print $1}')" = "$expected_release_launcher"
test "$(sha256sum "$distro_wheel" | awk '{print $1}')" = "$expected_distro"
test "$(sha256sum "$deployment_dir/patches/memory_pool_host_fluxon_metadata_only.py" | awk '{print $1}')" = "$expected_memory_pool"
test "$(sha256sum "$deployment_dir/patches/unified_radix_cache_e44_r61_tp_execute_commit.py" | awk '{print $1}')" = "$expected_radix_source"
test "$(sha256sum "$deployment_dir/patches/hicache_fluxon_e44_r54_prefetch_timeline_observe.py" | awk '{print $1}')" = "$expected_adapter_source"
test "$(sha256sum "$deployment_dir/patches/scheduler_e44_r54_prefetch_timeline_observe.py" | awk '{print $1}')" = "$expected_scheduler"
test "$(sha256sum "$deployment_dir/fluxon_sgl_kernel_ops_cuda13.so" | awk '{print $1}')" = "$expected_kernel_library"
test "$(sha256sum "$deployment_dir/fluxon_sgl_kernel_loader.py" | awk '{print $1}')" = "$expected_kernel_loader"
test "$(sha256sum "$deployment_dir/patch_fluxon_f_kernel_loader.py" | awk '{print $1}')" = "$expected_kernel_patcher"
test "$(sha256sum "$deployment_dir/patch_fluxon_f_gdr_off.py" | awk '{print $1}')" = "$expected_gdr_off_patcher"
(
  cd "$release"
  sha256sum -c fluxon_release.sha256 >/dev/null
  cd ext_images
  sha256sum -c ext_images.sha256 >/dev/null
)

if [[ -e "$runtime_root" ]]; then
  echo "refusing to overwrite an existing F runtime: $runtime_root" >&2
  exit 1
fi
install -d -m 0755 "$runtime_root/evidence" "$gpu_root"
install -d -m 0755 "$cuda_home"
for name in bin nvvm include lib64; do
  case "$name" in
    bin) target="$cuda_toolkit_root/bin" ;;
    nvvm) target="$cuda_toolkit_root/nvvm" ;;
    include) target="$cuda_toolkit_root/targets/x86_64-linux/include" ;;
    lib64) target="$cuda_toolkit_root/targets/x86_64-linux/lib" ;;
  esac
  ln -s "$target" "$cuda_home/$name"
done

# 31772 has Python's venv module but not the ensurepip package.  Build the new
# prefix without pip, then expose the sealed base venv as a read-only dependency
# layer.  pip still installs the selected release into this prefix because sys.prefix is $venv;
# the import gate below independently pins SGLang and Fluxon to this runtime.
"$base_venv/bin/python" -m venv --without-pip --system-site-packages "$venv"
base_site="$($base_venv/bin/python - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
venv_site="$($venv/bin/python - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
printf '%s\n' "$base_site" > "$venv_site/fluxon_f_base_venv.pth"
test "$("$venv/bin/python" -m pip --version | awk '{print $1}')" = pip

"$base_venv/bin/python" "$release/install.py" \
  --release-dir "$release" \
  --src-root "$src_root" \
  --venv-dir "$venv" \
  --sha256-file fluxon_release.sha256 \
  --tar-name pylib_src.tar.gz \
  --wheel "$wheel_name"

"$venv/bin/python" -m pip install --no-index --no-deps --force-reinstall "$distro_wheel"

test -d "$base_site/sglang"
rm -rf -- "$venv_site/sglang"
cp -a -- "$base_site/sglang" "$venv_site/sglang"

mem_cache="$venv_site/sglang/srt/mem_cache"
install -m 0444 "$deployment_dir/fluxon_sgl_kernel_loader.py" \
  "$venv_site/fluxon_sgl_kernel_loader.py"
install -m 0555 "$deployment_dir/fluxon_sgl_kernel_ops_cuda13.so" \
  "$venv_site/fluxon_sgl_kernel_ops_cuda13.so"
install -m 0644 "$deployment_dir/patches/memory_pool_host_fluxon_metadata_only.py" \
  "$mem_cache/memory_pool_host.py"
PYTHONDONTWRITEBYTECODE=1 "$base_venv/bin/python" -B \
  "$deployment_dir/patch_fluxon_f_kernel_loader.py" \
  --source "$deployment_dir/patches/unified_radix_cache_e44_r61_tp_execute_commit.py" \
  --output "$radix_kernel_loaded" \
  --manifest "$kernel_loader_patch_manifest"
PYTHONDONTWRITEBYTECODE=1 "$base_venv/bin/python" -B \
  "$deployment_dir/patch_fluxon_f_gdr_off.py" \
  --source "$radix_kernel_loaded" \
  --output "$mem_cache/unified_radix_cache.py" \
  --manifest "$gdr_off_patch_manifest"
PYTHONDONTWRITEBYTECODE=1 "$base_venv/bin/python" -B \
  "$deployment_dir/patch_fluxon_f_storage_metrics_compat.py" \
  --source "$deployment_dir/patches/hicache_fluxon_e44_r54_prefetch_timeline_observe.py" \
  --output "$mem_cache/storage/fluxon/hicache_fluxon.py" \
  --manifest "$metrics_compat_manifest"
install -m 0644 "$deployment_dir/patches/scheduler_e44_r54_prefetch_timeline_observe.py" \
  "$venv_site/sglang/srt/managers/scheduler.py"

test "$(sha256sum "$mem_cache/memory_pool_host.py" | awk '{print $1}')" = "$expected_memory_pool"
test "$(sha256sum "$mem_cache/unified_radix_cache.py" | awk '{print $1}')" = "$expected_radix"
test "$(sha256sum "$mem_cache/storage/fluxon/hicache_fluxon.py" | awk '{print $1}')" = "$expected_adapter_compat"
test "$(sha256sum "$venv_site/sglang/srt/managers/scheduler.py" | awk '{print $1}')" = "$expected_scheduler"
test "$(sha256sum "$venv_site/fluxon_sgl_kernel_loader.py" | awk '{print $1}')" = "$expected_kernel_loader"
test "$(sha256sum "$venv_site/fluxon_sgl_kernel_ops_cuda13.so" | awk '{print $1}')" = "$expected_kernel_library"

install -m 0755 "$deployment_dir/fluxon_wait_ready.sh" "$gpu_root/fluxon_wait_ready.sh"
PYTHONDONTWRITEBYTECODE=1 "$venv/bin/python" -B "$deployment_dir/derive_fluxon_f_launcher.py" \
  --source "$release/start_gpu_stack_owner_numa1_ssd.sh" \
  --output "$derived_launcher" \
  --manifest "$derive_manifest"
bash -n "$derived_launcher"

pyo3_dir="$venv_site/fluxon_pyo3"
pyo3_libs="$venv_site/fluxon_pyo3.libs"
test "$(sha256sum "$pyo3_dir/fluxon_pyo3.abi3.so" | awk '{print $1}')" = "$expected_pyo3"
test "$(sha256sum "$pyo3_libs/libfluxon_commu_core.so" | awk '{print $1}')" = "$expected_core"
test "$(sha256sum "$pyo3_libs/libfluxon_rdma_probe.so" | awk '{print $1}')" = "$expected_probe"

PYTHONDONTWRITEBYTECODE=1 \
LD_LIBRARY_PATH="$pyo3_dir:$pyo3_libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu" \
IBV_DRIVERS_PATH="$pyo3_libs/libibverbs.d" \
"$venv/bin/python" -B - "$venv" <<'PY'
from pathlib import Path
import inspect
import sys

from fluxon_sgl_kernel_loader import CUDA_OPS, load_fluxon_sgl_kernel_ops

kernel_library = load_fluxon_sgl_kernel_ops()
import torch
import distro
import fluxon_py
import fluxon_pyo3
import sglang
import sglang.srt.mem_cache.storage.backend_factory as backend_factory
import sglang.srt.mem_cache.storage.fluxon.hicache_fluxon as hicache_fluxon
import sglang.srt.mem_cache.unified_radix_cache as unified_radix_cache

root = str(Path(sys.argv[1]).resolve()) + "/"
if not str(kernel_library).startswith(root):
    raise SystemExit(f"kernel library escaped isolated F venv: {kernel_library}")
for name in CUDA_OPS:
    if not torch._C._dispatch_has_kernel_for_dispatch_key(
        f"sgl_kernel::{name}", "CUDA"
    ):
        raise SystemExit(f"focused Fluxon CUDA op missing: {name}")
for module in (fluxon_py, sglang):
    if not str(Path(module.__file__).resolve()).startswith(root):
        raise SystemExit(f"module escaped isolated F venv: {module.__name__}={module.__file__}")
if "fluxon" not in backend_factory.StorageBackendFactory._registry:
    raise SystemExit("Fluxon storage backend is not registered")
source = Path(hicache_fluxon.__file__).read_text(encoding="utf-8")
if "_local_fast_put_start_use_direct" not in source:
    raise SystemExit("sealed direct local-fast-put compatibility path is missing")
if "This sealed SGLang base predates Fluxon's L2/IO StorageMetrics" not in source:
    raise SystemExit("Fluxon F StorageMetrics compatibility gate is missing")
if getattr(unified_radix_cache, "_FLUXON_GPU_DIRECT_STAGING_ENABLED", None) is not False:
    raise SystemExit("Fluxon F GDR-off gate is not literal False")
radix_source = Path(unified_radix_cache.__file__).read_text(encoding="utf-8")
for marker in (
    "Fluxon GPU-direct staging disabled: mode=cpu_h2d_only",
    'gpu_admission_block_reason = "disabled"',
):
    if marker not in radix_source:
        raise SystemExit(f"Fluxon F GDR-off marker is missing: {marker}")
signature = str(inspect.signature(fluxon_pyo3.KvClient.local_fast_put_start))
for name in ("keys", "value_len", "make_replica_task_mask", "atomic_group_lens"):
    if name not in signature:
        raise SystemExit(f"selected-release PyO3 signature missing {name}: {signature}")
print(f"isolated F import gate passed: sglang={sglang.__file__} fluxon={fluxon_py.__file__} distro={distro.__version__}")
PY

"$venv/bin/python" - "$runtime_root" "$release" "$base_venv" "$venv_site" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

runtime, release, base, site = map(Path, sys.argv[1:])
paths = {
    "release_manifest": release / "fluxon_release.sha256",
    "release_wheel": release / "fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl",
    "base_venv_pth": site / "fluxon_f_base_venv.pth",
    "cuda_nvcc": runtime / "cuda/bin/nvcc",
    "cuda_header": runtime / "cuda/include/cuda.h",
    "derived_launcher": runtime / "fluxon_f1/start_gpu_stack_owner_tp2x2_f.sh",
    "storage_metrics_compat_manifest": runtime / "evidence/storage_metrics_compat.json",
    "kernel_loader_patch_manifest": runtime / "evidence/kernel_loader_patch.json",
    "gdr_off_patch_manifest": runtime / "evidence/gdr_off_patch.json",
    "unified_radix_cache_kernel_loaded": runtime / "evidence/unified_radix_cache_kernel_loaded.py",
    "kernel_loader": site / "fluxon_sgl_kernel_loader.py",
    "kernel_library": site / "fluxon_sgl_kernel_ops_cuda13.so",
    "memory_pool_host": site / "sglang/srt/mem_cache/memory_pool_host.py",
    "unified_radix_cache": site / "sglang/srt/mem_cache/unified_radix_cache.py",
    "hicache_fluxon": site / "sglang/srt/mem_cache/storage/fluxon/hicache_fluxon.py",
    "scheduler": site / "sglang/srt/managers/scheduler.py",
}
def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
out = {
    "schema_version": 1,
    "runtime_root": str(runtime),
    "release": str(release),
    "base_venv": str(base),
    "base_site_packages": (site / "fluxon_f_base_venv.pth").read_text(encoding="utf-8").strip(),
    "cuda_home": str(runtime / "cuda"),
    "cuda_links": {
        name: str((runtime / "cuda" / name).readlink())
        for name in ("bin", "nvvm", "include", "lib64")
    },
    "isolated_venv": str(runtime / "venv"),
    "files": {name: {"path": str(path), "sha256": digest(path)} for name, path in paths.items()},
}
(runtime / "evidence/runtime_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(json.dumps(out, sort_keys=True))
PY

echo "prepared isolated Fluxon F GPU runtime: $runtime_root"
