#!/usr/bin/env bash
# Project-local environment only. No sudo, no changes to existing Conda environments.
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
STUDIO_CONDA="${STUDIO_CONDA:-$(command -v conda || true)}"
STUDIO_CONDA="${STUDIO_CONDA:-$HOME/miniforge3/bin/conda}"
if [[ ! -x "$STUDIO_CONDA" && -x "$HOME/anaconda3/bin/conda" ]]; then STUDIO_CONDA="$HOME/anaconda3/bin/conda"; fi
STUDIO_RUNTIME="${STUDIO_RUNTIME:-$STUDIO_ROOT/.runtime}"
export STUDIO_RUNTIME
if [[ ! -x "$STUDIO_CONDA" ]]; then printf "%s\n" "Conda가 필요합니다. Miniforge를 설치하거나 STUDIO_CONDA를 지정하세요." >&2; exit 1; fi
if [[ ! -x "$STUDIO_RUNTIME/bin/python" ]]; then
  "$STUDIO_CONDA" create --prefix "$STUDIO_RUNTIME" python=3.10 pip -y
fi
STUDIO_PYTHON="$STUDIO_RUNTIME/bin/python"
# Apply the versions actually verified by the clean Ubuntu installation to all
# pip subprocesses, including transitive build/runtime dependency resolution.
if [[ "${STUDIO_VIEWER_ONLY:-0}" != 1 ]]; then
  export PIP_CONSTRAINT="$STUDIO_ROOT/requirements-runtime-constraints.txt"
fi
"$STUDIO_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,10), "Python 3.10 required"'
if [[ -e .git ]]; then git submodule update --init --recursive; fi
"$STUDIO_PYTHON" -m pip install pip==23.3.1 setuptools==68.2.2 wheel ninja
if [[ "${STUDIO_VIEWER_ONLY:-0}" == 1 ]]; then
 "$STUDIO_PYTHON" -m pip install -r requirements-viewer.txt
 "$STUDIO_PYTHON" -m pip install -r requirements-studio.txt
 printf '%s\n' '결과 보기용 설치입니다. SAM과 GPU 학습은 사용할 수 없습니다.'
else
"$STUDIO_PYTHON" -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu118
"$STUDIO_PYTHON" -m pip install -r requirements-anchor.txt
if [[ ! -x "$STUDIO_RUNTIME/nvvm/bin/cicc" ]]; then
  "$STUDIO_CONDA" install --prefix "$STUDIO_RUNTIME" --override-channels -c nvidia \
    --no-deps -y cuda-nvcc=11.8.89 cuda-cudart=11.8.89 cuda-cudart-dev=11.8.89 \
    cuda-cccl=11.8.89 cuda-driver-dev=11.8.89
fi
export CUDA_HOME="${STUDIO_CUDA_HOME:-$STUDIO_RUNTIME}"
export PATH="$CUDA_HOME/bin:$PATH"
export CC="${STUDIO_CC:-/usr/bin/gcc-11}"
export CXX="${STUDIO_CXX:-/usr/bin/g++-11}"
export MAX_JOBS="${STUDIO_MAX_JOBS:-4}"
if [[ -n "${STUDIO_CUDA_ARCH_LIST:-}" ]]; then
  export TORCH_CUDA_ARCH_LIST="$STUDIO_CUDA_ARCH_LIST"
else
  TORCH_CUDA_ARCH_LIST="$("$STUDIO_PYTHON" -c 'import torch; print(";".join(f"{a}.{b}" for a,b in sorted({torch.cuda.get_device_capability(i) for i in range(torch.cuda.device_count())})))')"
  export TORCH_CUDA_ARCH_LIST
fi
"$STUDIO_PYTHON" -c 'import torch; assert torch.__version__.split("+")[0] == "2.5.1"; assert torch.version.cuda == "11.8"; assert torch.cuda.is_available()'
STUDIO_BUILD_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/m4ml-studio/native-build"
mkdir -p "$STUDIO_BUILD_DIR"
"$STUDIO_PYTHON" -c 'import shutil,sys; from pathlib import Path; root=Path(sys.argv[1]); out=Path(sys.argv[2]); [shutil.copytree(root/p,out/p.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns(".git","build","*.egg-info","__pycache__")) for p in [Path("submodules/diff-surfel-rasterization"),Path("submodules/simple-knn")]]' "$STUDIO_ROOT" "$STUDIO_BUILD_DIR"
"$STUDIO_PYTHON" -m pip install --no-build-isolation "$STUDIO_BUILD_DIR/diff-surfel-rasterization" "$STUDIO_BUILD_DIR/simple-knn"
"$STUDIO_PYTHON" scripts/apply_sam_patches.py
"$STUDIO_PYTHON" -m pip install --no-deps --no-build-isolation -e ./vendor/sam3
"$STUDIO_PYTHON" -m pip install -r requirements-studio.txt
fi
if [[ ! -f frontend/dist/index.html || "${STUDIO_REBUILD_UI:-0}" == 1 ]]; then
  npm ci --prefix frontend
  npm run build --prefix frontend
fi
printf '%s\n' '기본 패키지 설치 완료. 실제 SAM 3.1·학습 호환성은 별도 검증이 필요합니다.'
if ! ./scripts/doctor.sh; then
 printf "%s\n" "패키지 설치 완료. GPU/체크포인트 진단에 미충족 항목이 있습니다. 앱의 환경 안내를 확인하세요."
fi
