#!/usr/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#echo $SCRIPT_DIR

#export HTTP_PROXY=http://127.0.0.1:3128
#export http_proxy=http://127.0.0.1:3128
export HTTPS_PROXY=http://127.0.0.1:3128
#export https_proxy=http://127.0.0.1:3128

#export NO_PROXY=localhost,127.0.0.1

export OPENCODE_CONFIG=${SCRIPT_DIR}/opencode.jsonc

${SCRIPT_DIR}/raw/opencode $*

