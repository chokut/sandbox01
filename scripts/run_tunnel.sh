#!/usr/bin/env bash
# set -euo pipefail

# Apptainer ネットワーク隔離 + HTTP プロキシ → ドメインソケット → リレー(relay.py) → 最終ターゲット
# 1つのスクリプトでリレーも自動起動し、終了時にリレーも含めて全部落とす。
#
# リレー(relay.py)はドメインソケット上で [2バイト長][host:port] のプレフィックスを
# 読み取り、そのターゲットに直接 TCP 接続する（HTTP_PROXY などの上位プロキシは経由しない）。
#
# 使い方:
#   ./scripts/run_tunnel.sh <target_host> <target_port> <image.sif> [app_command...]
# 例:
#   ./scripts/run_tunnel.sh example.com 443 my-image.sif my-app
#
# 備考: target_host/target_port はドキュメント用。実際の接続先は HTTP プロキシ リクエストで
# 指定されたターゲットをリレーが動的に使用する。

set -euo pipefail

IMAGE="${1:?<image.sif> required}"
shift 3 || true
APP_CMD=("${@:-}")

# 自分スクリプトのディレクトリ（リレー・プロキシスクリプト参照用）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELAY_SCRIPT="${SCRIPT_DIR}/relay.py"
PROXY_SCRIPT="${SCRIPT_DIR}/http_proxy_to_uds.py"
CONTAINER_PROXY_PATH="/opt/http_proxy_to_uds.py"
#PROXY_SCRIPT="${SCRIPT_DIR}/http_connect_proxy.py"
#CONTAINER_PROXY_PATH="/opt/http_connect_proxy.py"

# ドメインソケットファイル（/tmp の直下、pid を含めて衝突回避）
SOCK_DIR="/tmp"
SOCK_FILE="${SOCK_DIR}/apptainer-tunnel-$$.sock"
SOCKPATH_FILE="${SOCK_DIR}/apptainer-tunnel-sockpath"

# クリーンアップ: リレー(relay.py)・コンテナ・ソケットファイルをすべて落とす
cleanup() {
    local rc=${?}
    echo "[cleanup] stopping all processes..."
    # コンテナプロセスを kill
    if [[ -n "${CONTAINER_PID:-}" ]] && kill -0 "${CONTAINER_PID}" 2>/dev/null; then
        kill "${CONTAINER_PID}" 2>/dev/null || true
        wait "${CONTAINER_PID}" 2>/dev/null || true
    fi
    # リレー(relay.py)を kill
    if [[ -n "${RELAY_PID:-}" ]] && kill -0 "${RELAY_PID}" 2>/dev/null; then
        kill "${RELAY_PID}" 2>/dev/null || true
        wait "${RELAY_PID}" 2>/dev/null || true
    fi
    # ソケットファイルとパス保存ファイルを削除
    rm -f "${SOCK_FILE}" "${SOCKPATH_FILE}"
    echo "[cleanup] done (rc=${rc})"
    exit "${rc}"
}

trap cleanup EXIT INT TERM

# スクリプト存在確認
if [[ ! -f "${RELAY_SCRIPT}" ]]; then
    echo "[error] リレースクリプトが見つかりません: ${RELAY_SCRIPT}" >&2
    exit 1
fi
if [[ ! -f "${PROXY_SCRIPT}" ]]; then
    echo "[error] プロキシスクリプトが見つかりません: ${PROXY_SCRIPT}" >&2
    exit 1
fi

# 既存ソケットファイルがあれば削除
rm -f "${SOCK_FILE}"

# ---- 1. リレー(relay.py)をバックグラウンド起動 ----
# ドメインソケットで待ち受け、HTTP プロキシ ターゲットに直接 TCP 接続（上位プロキシ経由しない）
python3 "${RELAY_SCRIPT}" "${SOCK_FILE}" &
RELAY_PID=$!

# ソケットパスを保存（コンテナ側で参照）
echo "${SOCK_FILE}" > "${SOCKPATH_FILE}"

echo "[relay] relay.py PID=${RELAY_PID} listening on ${SOCK_FILE} (direct TCP target)"

# ソケットファイルが作成されるまで待つ（最長 5 秒）
for i in $(seq 1 50); do
    if [[ -S "${SOCK_FILE}" ]]; then
        break
    fi
    sleep 0.1
done

if [[ ! -S "${SOCK_FILE}" ]]; then
    echo "[error] ドメインソケットが作成されませんでした: ${SOCK_FILE}" >&2
    exit 1
fi

# ---- 2. Apptainer コンテナをフォアグラウンド起動 ----
# --network none: ネットワーク隔離（loopback のみ利用可能）
# --bind: ドメインソケットファイルとプロキシスクリプトをコンテナ内と同パスでマウント
# --env: プロキシがソケットパス・アプリがプロキシを参照するための環境変数
echo "[container] starting apptainer (image=${IMAGE})"
apptainer run \
    --net \
    --network none \
    --bind "${SOCK_FILE}:${SOCK_FILE}" \
    --bind "${PROXY_SCRIPT}:${CONTAINER_PROXY_PATH}" \
    --env TUNNEL_SOCK="${SOCK_FILE}" \
    --env http_proxy=http://127.0.0.1:3128 \
    "${IMAGE}" \
    /bin/sh -c "
	python3 ${CONTAINER_PROXY_PATH} &
        PROXY_PID=\\\$!
	trap \\\"kill \\\$PROXY_PID\\\" EXIT INT TERM
	/bin/bash
    "
        #python3 /opt/http_proxy_to_uds.py &

    #--env http_proxy=http://127.0.0.1:3128 \
    #--env HTTPS_PROXY=http://127.0.0.1:3128 \
    #/bin/bash -c "
    #    python3 /opt/container_side.py "\\\$APPTAINER_SOCK" &
    #    CONTAINER_AGENT_PID=\\\$!
    #    trap \\\"kill \\\${CONTAINER_AGENT_PID}\\\" EXIT INT TERM
    #    #/bin/bash
    #    /bin/sh -c \\\"${APP_CMD}\\\"
    #"

# 到这里はコンテナ終了後。trap cleanup EXIT がクリーンアップを実行する。
