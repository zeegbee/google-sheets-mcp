"""Smoke-тест: сервер запускается по stdio и отдаёт все инструменты.

Ключ Google не нужен — проверяется только MCP-протокол и сообщение об ошибке
при отсутствии ключа.

Запуск: python tests/smoke_test.py [команда запуска сервера...]
По умолчанию сервер запускается как `python server.py`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

EXPECTED_TOOLS = {
    "list_spreadsheets",
    "get_spreadsheet_info",
    "create_spreadsheet",
    "share_spreadsheet",
    "add_sheet",
    "rename_sheet",
    "delete_sheet",
    "read_range",
    "read_records",
    "write_range",
    "append_rows",
    "clear_range",
    "find_cells",
}

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    cmd = sys.argv[1:] or [sys.executable, str(ROOT / "server.py")]
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_SERVICE_ACCOUNT_FILE"}
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
    )

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def receive(msg_id: int) -> dict:
        for line in proc.stdout:
            msg = json.loads(line)
            if msg.get("id") == msg_id:
                return msg
        raise RuntimeError(f"Сервер закрыл stdout, не ответив на запрос {msg_id}")

    try:
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "1"},
            },
        })
        assert receive(1)["result"]["serverInfo"]["name"] == "google-sheets"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {t["name"] for t in receive(2)["result"]["tools"]}
        assert tools == EXPECTED_TOOLS, f"Расхождение инструментов: {tools ^ EXPECTED_TOOLS}"

        send({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_spreadsheets", "arguments": {}},
        })
        result = receive(3)["result"]
        assert result["isError"], result
        assert "GOOGLE_SERVICE_ACCOUNT_FILE" in result["content"][0]["text"] or \
            "service_account.json" in result["content"][0]["text"], result
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)

    print(f"OK: {len(tools)} инструментов, обработка ошибок работает")


if __name__ == "__main__":
    main()
