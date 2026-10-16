#!/usr/bin/env bash
# Project-local environment only. No sudo, no changes to existing Conda environments.
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
STUDIO_CONDA="${STUDIO_CONDA:-$HOME/anaconda3/bin/conda}"
if [[ ! -x "$STUDIO_ROOT/.runtime/bin/python" ]]; then
  "$STUDIO_CONDA" create --prefix "$STUDIO_ROOT/.runtime" python=3.10 pip -y
fi
STUDIO_PYTHON="$STUDIO_ROOT/.runtime/bin/python"
"$STUDIO_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,10), "Python 3.10 required"'
git submodule update --init --recursive
"$STUDIO_PYTHON" -m pip install pip==23.3.1 setuptools==68.2.2 wheel ninja
"$STUDIO_PYTHON" -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu118
"$STUDIO_PYTHON" -m pip install -r requirements-anchor.txt
if [[ ! -x "$STUDIO_ROOT/.runtime/nvvm/bin/cicc" ]]; then
  "$STUDIO_CONDA" install --prefix "$STUDIO_ROOT/.runtime" --override-channels -c nvidia \
    --no-deps -y cuda-nvcc=11.8.89 cuda-cudart=11.8.89 cuda-cudart-dev=11.8.89 \
    cuda-cccl=11.8.89 cuda-driver-dev=11.8.89
fi
export CUDA_HOME="${STUDIO_CUDA_HOME:-$STUDIO_ROOT/.runtime}"
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
"$STUDIO_PYTHON" -m pip install --no-build-isolation ./submodules/diff-surfel-rasterization ./submodules/simple-knn
"$STUDIO_PYTHON" scripts/apply_sam_patches.py
"$STUDIO_PYTHON" -m pip install --no-deps --no-build-isolation -e ./vendor/sam3
"$STUDIO_PYTHON" -m pip install -r requirements-studio.txt
npm ci --prefix frontend
npm run build --prefix frontend
printf '%s\n' '기본 패키지 설치 완료. 실제 SAM 3.1·학습 호환성은 별도 검증이 필요합니다.'
exec ./scripts/doctor.sh
