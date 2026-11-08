#!/bin/bash
#
# post01.sh - llmproxy へ curl で LLM リクエストを送るサンプル
#
# 使用例:
#   ./post01.sh
#   PROXY_URL=http://127.0.0.1:8080 API_KEY=sk-xxx ./post01.sh
#

set -euo pipefail

# --- 設定（環境変数で上書き可能） ---
PROXY_URL="${PROXY_URL:-http://127.0.0.1:8888}"
API_KEY="${API_KEY:-}"
MODEL="${MODEL:-nvidia/nemotron-3.5-super-vl:free}"
#MODEL="${MODEL:-deepseek/deepseek-v4-flash-0731}"

# リクエスト先エンドポイント（llmproxy は /v1.* を上流へプロキシ）
ENDPOINT="${PROXY_URL}/v1/chat/completions"

echo "=== llmproxy へ LLM リクエストを送信 ==="
echo "URL: ${ENDPOINT}"
echo "Model: ${MODEL}"
echo ""

# --- リクエストボディ（JSON） ---
BODY=$(cat <<EOF
{
  "model": "${MODEL}",
  "messages": [
    {
      "role": "system",
      "content": "あなたは親切なアシスタントです。日本語で回答してください。"
    },
    {
      "role": "user",
      "content": "こんにちは！自分について教えてください。"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 32,
  "stream": false
}
EOF
)

# --- curl で POST リクエスト送信 ---
#curl -s -X POST "${ENDPOINT}" \
#  -H "Content-Type: application/json" \
#  ${API_KEY:+-H "Authorization: Bearer ${API_KEY}"} \
#  -d "${BODY}" \
#  | jq .
curl -s -p -X POST "${ENDPOINT}" \
  -H "Content-Type: application/json" \
  ${API_KEY:+-H "Authorization: Bearer ${API_KEY}"} \
  -d "${BODY}" 

echo ""
echo "=== リクエスト完了 ==="
