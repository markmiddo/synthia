#!/bin/bash
# Launch Synthia with cuDNN libraries in path

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_VERSION=$(./venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
CUDNN_LIB="$SCRIPT_DIR/venv/lib/python${PYTHON_VERSION}/site-packages/nvidia/cudnn/lib"
CUBLAS_LIB="$SCRIPT_DIR/venv/lib/python${PYTHON_VERSION}/site-packages/nvidia/cublas/lib"

export LD_LIBRARY_PATH="$CUDNN_LIB:$CUBLAS_LIB:$LD_LIBRARY_PATH"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

cd "$SCRIPT_DIR"
source venv/bin/activate
./venv/bin/python -m synthia.main "$@"
