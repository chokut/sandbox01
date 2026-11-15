#
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4 
#

import json
import os
import requests
import subprocess

# 接続先設定（Ollama、vLLM、LM Studio、OpenAI本家などに合わせて変更）
API_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:8888/v1") + "/chat/completions"
API_KEY = os.getenv("OPENAI_API_KEY", "dummy-key")
MODEL = os.getenv("OPENAI_MODEL", "nvidia/nemotron-3.5-super-vl:free")

def bash(command: str, timeout: int = 90) -> str:
    try:
        res = subprocess.run(
            command, shell=True, #cwd=str(WORKSPACE_DIR),
            capture_output=True, text=True, timeout=timeout
        )
        out = f"Exit Code: {res.returncode}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        return out[:8000]
    except Exception as e:
        return f"Error: {e}"

AVAILABLE_FUNCTIONS = {
    "bash": bash,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "作業ディレクトリ内でシェルコマンドを実行します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
]

def call_chat_api(messages: list) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
    }
    response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()

system_text = '''\
あなたは親切なアシスタントです。必要に応じてツールを使って回答してください。
OSはubuntuです。最初に使えるコマンドを把握してください。
ファイルの読み書きはbashを通して行ってください。ファイルを読み込む前にサイズを確認して、
一気に大きなファイルを読み込むことは避けてください。
'''

def main():
    messages = [
        {"role": "system", "content": system_text}
    ]

    print("チャットを開始します（終了するには 'exit' と入力）")
    while True:
        user_input = input("\nあなた: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # ツール呼び出しが連鎖するケースにも対応するため while で回す
        while True:
            data = call_chat_api(messages)
            assistant_msg = data["choices"][0]["message"]
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls")
            if not tool_calls:
                # ツール呼び出しがなければ通常のテキスト応答を表示してターン終了
                print(f"AI: {assistant_msg.get('content', '')}")
                break

            # 3. 要求されたツールをすべて実行し、結果を履歴に追加
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                func_args = json.loads(tool_call["function"]["arguments"])
                print(f"  [ツール実行] {func_name}({func_args})")

                func = AVAILABLE_FUNCTIONS.get(func_name)
                result = func(**func_args) if func else f"Error: {func_name} は未定義です"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": str(result),
                })

if __name__ == "__main__":
    main()
