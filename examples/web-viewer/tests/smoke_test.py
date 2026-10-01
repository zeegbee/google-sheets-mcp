"""Smoke-тест: веб-сервер стартует, поднимает MCP-сервер и отдаёт API.

Настоящий ключ Google не нужен — проверяется связка HTTP -> MCP -> server.py
и то, что ошибка MCP-сервера доходит до клиента понятным текстом.

Запуск:
    python tests/smoke_test.py            # MCP-сервер из корня репозитория
    python tests/smoke_test.py --docker   # MCP-сервер в Docker-образе google-sheets-mcp
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    docker = "--docker" in sys.argv[1:]
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as tmp:
        if docker:
            # В режиме docker файл ключа должен существовать, чтобы его смонтировать.
            key = Path(tmp) / "service_account.json"
            key.write_text("{}", encoding="utf-8")
        else:
            key = Path(tmp) / "missing.json"

        env = os.environ | {
            "PORT": str(port),
            "GOOGLE_SERVICE_ACCOUNT_FILE": str(key),
            "PYTHONIOENCODING": "utf-8",
        }
        cmd = [sys.executable, str(ROOT / "app.py")] + (["--docker"] if docker else [])
        proc = subprocess.Popen(cmd, env=env, cwd=ROOT)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(base + "/", timeout=1)
                    break
                except OSError:
                    if proc.poll() is not None:
                        raise RuntimeError(f"app.py завершился с кодом {proc.returncode}")
                    time.sleep(0.5)
            else:
                raise RuntimeError("Веб-сервер не запустился за 30 секунд")

            status, body = get(base + "/api/status")
            assert status == 200 and body["data"]["mode"] == ("docker" if docker else "local"), body

            status, body = get(base + "/api/info")
            assert status == 400 and "spreadsheet" in body["error"], body

            # Запрос проходит через MCP до server.py и возвращается ошибкой ключа
            status, body = get(base + "/api/spreadsheets")
            assert status == 400 and body.get("error"), (status, body)
            if not docker:
                assert "Файл ключа не найден" in body["error"], body
        finally:
            proc.terminate()
            proc.wait(timeout=30)

    print(f"OK ({'docker' if docker else 'local'}): HTTP -> MCP -> server.py работает")


if __name__ == "__main__":
    main()
