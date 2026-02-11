#!/bin/bash
# Launch Synthia with cuDNN libraries in path

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_VERSION=$(./venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
CT2_LIBS="$SCRIPT_DIR/venv/lib/python${PYTHON_VERSION}/site-packages/ctranslate2.libs"
NVIDIA_CUDNN="$SCRIPT_DIR/venv/lib/python${PYTHON_VERSION}/site-packages/nvidia/cudnn/lib"
NVIDIA_CUBLAS="$SCRIPT_DIR/venv/lib/python${PYTHON_VERSION}/site-packages/nvidia/cublas/lib"

export LD_LIBRARY_PATH="$CT2_LIBS:$NVIDIA_CUDNN:$NVIDIA_CUBLAS:$LD_LIBRARY_PATH"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

cd "$SCRIPT_DIR"
source venv/bin/activate
./venv/bin/python -m synthia.main "$@"
