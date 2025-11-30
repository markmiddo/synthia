#!/bin/bash
# Launch LinuxVoice with cuDNN libraries in path

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CUDNN_LIB="$SCRIPT_DIR/venv/lib/python3.10/site-packages/nvidia/cudnn/lib"
CUBLAS_LIB="$SCRIPT_DIR/venv/lib/python3.10/site-packages/nvidia/cublas/lib"

export LD_LIBRARY_PATH="$CUDNN_LIB:$CUBLAS_LIB:$LD_LIBRARY_PATH"

cd "$SCRIPT_DIR"
source venv/bin/activate
python main.py "$@"
