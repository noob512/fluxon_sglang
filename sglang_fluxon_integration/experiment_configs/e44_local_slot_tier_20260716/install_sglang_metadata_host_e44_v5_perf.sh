#!/usr/bin/env bash
set -euo pipefail

source_file="${1:?missing patched memory_pool_host.py}"
site="${2:-/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages}"
target="$site/sglang/srt/mem_cache/memory_pool_host.py"
base_sha=ed6964840ea836f080c02b74c1f11545fa5c2d87b391236a8b12278d979e21e4
patched_sha=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878

test "$(sha256sum "$source_file" | awk '{print $1}')" = "$patched_sha"
current_sha="$(sha256sum "$target" | awk '{print $1}')"
case "$current_sha" in
  "$base_sha")
    backup="${target}.bak_before_fluxon_metadata_only_20260718"
    test ! -e "$backup"
    install -m 0644 "$target" "$backup"
    ;;
  "$patched_sha") ;;
  *)
    echo "unexpected memory_pool_host.py sha256: $current_sha" >&2
    exit 1
    ;;
esac

install -m 0644 "$source_file" "$target"
python_bin="${site%/lib/python3.10/site-packages}/bin/python"
"$python_bin" - <<PY
from pathlib import Path
p = Path("$target")
compile(p.read_text(), str(p), "exec")
print("syntax_ok", p)
PY
test "$(sha256sum "$target" | awk '{print $1}')" = "$patched_sha"

