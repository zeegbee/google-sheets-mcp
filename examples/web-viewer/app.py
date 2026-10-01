"""Веб-интерфейс для просмотра Google Таблиц через google-sheets-mcp.

Бэкенд — MCP-клиент: при старте запускает server.py из google-sheets-mcp
как подпроцесс (stdio) и держит одно соединение, а браузеру отдаёт JSON API
и статическую страницу.

Запуск:
    python app.py            # MCP-сервер из локального .venv, http://127.0.0.1:8000
    python app.py --docker   # MCP-сервер в Docker-контейнере

Переменные окружения (все необязательные):
    MCP_MODE                     — local (по умолчанию) или docker; флаг --docker важнее
    MCP_SERVER_DIR               — папка с server.py (по умолчанию корень репозитория, ../..)
    MCP_PYTHON                   — интерпретатор для server.py (по умолчанию .venv из MCP_SERVER_DIR)
    MCP_DOCKER_IMAGE             — образ для режима docker (по умолчанию google-sheets-mcp)
    GOOGLE_SERVICE_ACCOUNT_FILE  — JSON-ключ (по умолчанию MCP_SERVER_DIR/service_account.json)
    HOST, PORT                   — адрес веб-сервера (127.0.0.1:8000)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from mcp import Client, StdioServerParameters
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
# Пример лежит в examples/web-viewer, server.py — в корне репозитория
MCP_DIR = Path(os.environ.get("MCP_SERVER_DIR", HERE.parent.parent)).resolve()
KEY_FILE = Path(
    os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", MCP_DIR / "service_account.json")
).resolve()
DOCKER_IMAGE = os.environ.get("MCP_DOCKER_IMAGE", "google-sheets-mcp")
MCP_MODE = os.environ.get("MCP_MODE", "local").lower()


def default_python() -> str:
    for candidate in (MCP_DIR / ".venv/Scripts/python.exe", MCP_DIR / ".venv/bin/python"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def local_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=os.environ.get("MCP_PYTHON", default_python()),
        args=[str(MCP_DIR / "server.py")],
        env={"GOOGLE_SERVICE_ACCOUNT_FILE": str(KEY_FILE), "PYTHONIOENCODING": "utf-8"},
        cwd=str(MCP_DIR),
    )


def docker_params() -> StdioServerParameters:
    # Ключ монтируется только для чтения туда, где его ждёт Dockerfile;
    # -i обязателен: MCP идёт через stdin/stdout контейнера.
    return StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-v", f"{KEY_FILE}:/secrets/service_account.json:ro",
            DOCKER_IMAGE,
        ],
    )


def check_docker() -> None:
    """Понятная ошибка при старте вместо падения на первом запросе."""
    if not shutil.which("docker"):
        sys.exit("Docker не найден в PATH. Установите Docker или запустите без --docker.")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("Docker не отвечает — запустите Docker Desktop.")
    if subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True).returncode != 0:
        sys.exit(
            f"Образ «{DOCKER_IMAGE}» не найден. Соберите его:\n"
            f"    docker build -t {DOCKER_IMAGE} \"{MCP_DIR}\""
        )
    if not KEY_FILE.is_file():
        sys.exit(f"Файл ключа не найден: {KEY_FILE}")


SERVER_PARAMS = docker_params() if MCP_MODE == "docker" else local_params()


class ToolFailed(Exception):
    """Инструмент MCP вернул ошибку (isError) — текст показываем пользователю."""


class McpBridge:
    """Одно долгоживущее MCP-соединение, которым владеет фоновая задача.

    anyio требует входить и выходить из контекста клиента в одной задаче,
    поэтому HTTP-обработчики не трогают клиента напрямую, а кладут вызовы
    в очередь. При обрыве соединения задача переподключается.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future]] = asyncio.Queue()

    async def run(self) -> None:
        while True:
            name, arguments, future = await self._queue.get()
            try:
                async with Client(SERVER_PARAMS, read_timeout_seconds=60) as client:
                    while True:
                        if not future.done():
                            future.set_result(await client.call_tool(name, arguments))
                        name, arguments, future = await self._queue.get()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Соединение упало: текущий вызов завершаем ошибкой,
                # следующий вызов поднимет новый подпроцесс.
                if not future.done():
                    future.set_exception(e)

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        # Вызовы выполняются по одному: подпроцесс один, gspread внутри синхронный.
        future = asyncio.get_running_loop().create_future()
        await self._queue.put((name, arguments, future))
        return parse_result(await future)


def parse_result(result: Any) -> Any:
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if result.is_error:
        message = "\n".join(texts) or "Неизвестная ошибка MCP-сервера"
        raise ToolFailed(re.sub(r"^Error executing tool \w+: ", "", message))
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        # MCPServer оборачивает не-объектные результаты (списки) в {"result": ...}
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except ValueError:
            return texts[0]
    return [json.loads(t) for t in texts]


bridge = McpBridge()


async def api(request: Request, tool: str, arguments: dict[str, Any]) -> JSONResponse:
    args = {k: v for k, v in arguments.items() if v not in (None, "")}
    try:
        return JSONResponse({"data": await bridge.call(tool, args)})
    except ToolFailed as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # падение подпроцесса, таймаут и т. п.
        return JSONResponse({"error": f"MCP-сервер недоступен: {e}"}, status_code=502)


def require(request: Request, name: str) -> str:
    value = request.query_params.get(name, "").strip()
    if not value:
        raise ValueError(f"Параметр «{name}» обязателен")
    return value


async def spreadsheets(request: Request) -> JSONResponse:
    return await api(request, "list_spreadsheets", {"query": request.query_params.get("q")})


async def info(request: Request) -> JSONResponse:
    try:
        spreadsheet = require(request, "spreadsheet")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return await api(request, "get_spreadsheet_info", {"spreadsheet": spreadsheet})


async def values(request: Request) -> JSONResponse:
    try:
        spreadsheet = require(request, "spreadsheet")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    q = request.query_params
    return await api(
        request,
        "read_range",
        {
            "spreadsheet": spreadsheet,
            "sheet": q.get("sheet"),
            "range": q.get("range"),
            "formulas": q.get("formulas") == "1",
        },
    )


async def status(request: Request) -> JSONResponse:
    return JSONResponse({"data": {"mode": MCP_MODE, "image": DOCKER_IMAGE if MCP_MODE == "docker" else None}})


async def index(request: Request) -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@asynccontextmanager
async def lifespan(app: Starlette):
    worker = asyncio.create_task(bridge.run())
    yield
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/spreadsheets", spreadsheets),
        Route("/api/info", info),
        Route("/api/values", values),
        Route("/api/status", status),
        Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Веб-интерфейс для google-sheets-mcp")
    parser.add_argument("--docker", action="store_true", help="запускать MCP-сервер в Docker")
    parser.add_argument("--image", help=f"Docker-образ (по умолчанию {DOCKER_IMAGE})")
    cli = parser.parse_args()

    if cli.image:
        DOCKER_IMAGE = cli.image
    if cli.docker:
        MCP_MODE = "docker"
    if MCP_MODE == "docker":
        check_docker()
        SERVER_PARAMS = docker_params()
        print(f"MCP-сервер: Docker-образ {DOCKER_IMAGE}")
    else:
        SERVER_PARAMS = local_params()
        print(f"MCP-сервер: {MCP_DIR / 'server.py'}")

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Откройте http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
