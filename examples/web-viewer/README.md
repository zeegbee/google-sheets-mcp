# Web Viewer — пример веб-интерфейса

Веб-интерфейс для просмотра Google Таблиц через этот MCP-сервер. Пример показывает,
как использовать google-sheets-mcp не из Claude, а из своего приложения через MCP-клиент.

```
Браузер ──HTTP/JSON──▶ app.py (MCP-клиент) ──stdio──▶ server.py ──▶ Google Sheets API
                                                     (python или docker)
```

Бэкенд сам запускает `server.py` из корня репозитория как подпроцесс — локально или
в Docker-контейнере — и вызывает инструменты `list_spreadsheets`, `get_spreadsheet_info`
и `read_range`.

## Возможности

- список таблиц, доступных сервисному аккаунту, с фильтром по названию;
- открытие любой таблицы по ссылке или ID;
- вкладки листов, чтение всего листа или диапазона (`A1:F50`);
- сортировка по клику на заголовок, поиск с подсветкой, режим «формулы»;
- ссылка вида `http://127.0.0.1:8000/?id=<ID>` сразу открывает таблицу;
- светлая и тёмная тема, адаптивная вёрстка.

## Запуск

Сначала настройте Google и положите ключ в `service_account.json` в корне репозитория —
см. [основной README](../../README.md#настройка-google). Команды ниже выполняются
из папки `examples/web-viewer`.

### Вариант 1: MCP-сервер локально

Виртуальное окружение сервера уже содержит все зависимости примера:

```bash
../../.venv/bin/python app.py          # Windows: ..\..\.venv\Scripts\python app.py
```

Или отдельное окружение: `pip install -r requirements.txt`, затем `python app.py`
(сервер всё равно запускается из `../../.venv`, если оно есть).

### Вариант 2: MCP-сервер в Docker

Сервер работает в контейнере (`docker run -i --rm`, ключ монтируется только для чтения):

```bash
docker build -t google-sheets-mcp ../..   # один раз
python app.py --docker                    # или MCP_MODE=docker
```

Другой образ: `python app.py --docker --image my-registry/google-sheets-mcp:1.0`.
Перед стартом проверяется, что Docker запущен, образ собран и ключ существует.

---

Откройте http://127.0.0.1:8000. Текущий режим (`local` / `docker`) виден в бейдже
рядом с заголовком страницы. Если порт занят: `PORT=8080 python app.py`
(PowerShell: `$env:PORT=8080; python app.py`).

## Настройки

Все переменные окружения необязательные.

| Переменная | По умолчанию |
|---|---|
| `MCP_MODE` | `local` или `docker` (флаг `--docker` важнее) |
| `MCP_SERVER_DIR` | корень репозитория (`../..`) |
| `MCP_PYTHON` | `.venv` из `MCP_SERVER_DIR`, иначе текущий интерпретатор (режим `local`) |
| `MCP_DOCKER_IMAGE` | `google-sheets-mcp` (режим `docker`) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `MCP_SERVER_DIR/service_account.json` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` |

> ⚠️ Интерфейс не требует авторизации: любой, кто откроет страницу, увидит все таблицы,
> доступные сервисному аккаунту. Не меняйте `HOST` на `0.0.0.0` без защиты (VPN, reverse proxy с паролем).

## API

| Запрос | MCP-инструмент |
|---|---|
| `GET /api/spreadsheets?q=` | `list_spreadsheets` |
| `GET /api/info?spreadsheet=` | `get_spreadsheet_info` |
| `GET /api/values?spreadsheet=&sheet=&range=&formulas=1` | `read_range` |
| `GET /api/status` | — (режим запуска MCP-сервера) |

Ответ — `{"data": ...}` или `{"error": "..."}`.

## Проверка

Smoke-тест поднимает веб-сервер и проверяет цепочку HTTP → MCP → server.py
(настоящий ключ не нужен):

```bash
python tests/smoke_test.py            # MCP-сервер локально
python tests/smoke_test.py --docker   # MCP-сервер в Docker
```

Оба варианта входят в CI репозитория (задача `web-viewer`).

## Файлы

```
├── app.py                 # веб-сервер (Starlette) и MCP-клиент
├── static/index.html      # интерфейс: HTML + CSS + JS без сборки
├── requirements.txt
└── tests/smoke_test.py    # smoke-тест
```
