# Google Sheets MCP Server

[![CI](https://github.com/zeegbee/google-sheets-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/zeegbee/google-sheets-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[MCP](https://modelcontextprotocol.io/)-сервер, который даёт Claude (или любому другому MCP-клиенту) доступ к Google Таблицам: чтение, запись, создание таблиц и листов, поиск, выдача доступа.

## Инструменты

| Инструмент | Что делает |
|---|---|
| `list_spreadsheets` | Список таблиц, доступных сервисному аккаунту (с фильтром по названию) |
| `get_spreadsheet_info` | Название, ссылка и листы таблицы с размерами |
| `create_spreadsheet` | Создать таблицу и сразу открыть доступ на ваш email (см. ограничение ниже) |
| `share_spreadsheet` | Выдать доступ: `reader` / `commenter` / `writer` |
| `add_sheet` / `rename_sheet` / `delete_sheet` | Управление листами |
| `read_range` | Прочитать диапазон (`A1:D10`) или весь лист, можно получить формулы |
| `read_records` | Прочитать лист как список объектов (первая строка — заголовки) |
| `write_range` | Записать двумерный массив в диапазон (формулы `=SUM(...)` работают) |
| `append_rows` | Добавить строки в конец данных |
| `clear_range` | Очистить диапазон или весь лист |
| `find_cells` | Найти ячейки с текстом на одном или всех листах |

Во всех инструментах `spreadsheet` — это ID таблицы или её полная ссылка, `sheet` — название листа (по умолчанию первый).

## Настройка Google

1. Откройте [Google Cloud Console](https://console.cloud.google.com/) и создайте проект (или выберите существующий).
2. **Включите оба API — по умолчанию в новом проекте они выключены**, и без них сервер работать не будет:
   - [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com) — чтение и запись данных, работа с листами;
   - [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) — список таблиц, создание и выдача доступа.

   Перейдите по каждой ссылке, убедитесь, что вверху выбран нужный проект, и нажмите **Enable** (**Включить**). То же самое можно сделать через **APIs & Services → Library**. После включения подождите 1–5 минут, пока изменение применится.
3. **APIs & Services → Credentials → Create credentials → Service account**. Создайте аккаунт, роли можно не назначать.
4. Откройте созданный сервисный аккаунт → **Keys → Add key → Create new key → JSON** и сохраните файл, например как `service_account.json` в корне проекта.
5. Скопируйте email сервисного аккаунта (вида `name@project.iam.gserviceaccount.com`) и **откройте ему доступ** к нужным таблицам через кнопку «Настройки доступа», как обычному пользователю.

> Сервисный аккаунт видит только таблицы, которыми с ним поделились, и те, что создал сам.

> **Ограничение на создание таблиц.** У новых сервисных аккаунтов квота Google Drive равна 0, поэтому `create_spreadsheet` вернёт ошибку «storage quota exceeded». В этом случае создайте таблицу вручную и откройте к ней доступ для сервисного аккаунта — все остальные инструменты работают. Создание работает, если у аккаунта есть квота (например, в Google Workspace с общими дисками).

### Частые ошибки

| Сообщение | Причина и решение |
|---|---|
| `Google Sheets API has not been used in project … or it is disabled` | Sheets API выключен — включите его (шаг 2). Ссылка на нужный проект есть прямо в тексте ошибки |
| `Google Drive API has not been used in project … or it is disabled` | Drive API выключен — включите его (шаг 2). Без него не работают `list_spreadsheets`, `create_spreadsheet`, `share_spreadsheet` |
| `Нет доступа (403)` / `Таблица не найдена` | Таблица не открыта для email сервисного аккаунта (шаг 5) или неверный ID/ссылка |
| `The user's Drive storage quota has been exceeded` | У сервисного аккаунта нулевая квота Drive — см. ограничение на создание таблиц выше |

> ⚠️ **Никогда не коммитьте JSON-ключ.** Файлы `service_account*.json`, `credentials*.json` и `.env` уже добавлены в `.gitignore`.

Ниже `/path/to/google-sheets-mcp` — путь к папке проекта, `/path/to/service_account.json` — путь к ключу. На Windows используйте пути вида `C:\path\to\...`, а в JSON экранируйте обратные слэши: `C:\\path\\to\\...`.

## Вариант 1: локально (Python)

Требуется Python 3.10+.

```bash
git clone https://github.com/zeegbee/google-sheets-mcp.git
cd google-sheets-mcp
python -m venv .venv
```

```bash
# Linux / macOS
.venv/bin/pip install -r requirements.txt
# Windows
.venv\Scripts\pip install -r requirements.txt
```

### Claude Code

```bash
claude mcp add google-sheets \
  -e GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service_account.json \
  -- /path/to/google-sheets-mcp/.venv/bin/python /path/to/google-sheets-mcp/server.py
```

На Windows интерпретатор лежит в `.venv\Scripts\python.exe`.

### Claude Desktop

Добавьте в конфиг (`%APPDATA%\Claude\claude_desktop_config.json` на Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` на macOS):

```json
{
  "mcpServers": {
    "google-sheets": {
      "command": "/path/to/google-sheets-mcp/.venv/bin/python",
      "args": ["/path/to/google-sheets-mcp/server.py"],
      "env": {
        "GOOGLE_SERVICE_ACCOUNT_FILE": "/path/to/service_account.json"
      }
    }
  }
}
```

и перезапустите Claude Desktop.

## Вариант 2: Docker

Python ставить не нужно, достаточно Docker.

```bash
git clone https://github.com/zeegbee/google-sheets-mcp.git
cd google-sheets-mcp
docker build -t google-sheets-mcp .
```

Ключ в образ не попадает — он монтируется при запуске в `/secrets/service_account.json` (только для чтения). MCP общается через stdin/stdout, поэтому обязателен флаг `-i`. Контейнер запускает сам MCP-клиент, вручную держать его запущенным не нужно.

### Claude Code

```bash
claude mcp add google-sheets -- docker run -i --rm \
  -v /path/to/service_account.json:/secrets/service_account.json:ro \
  google-sheets-mcp
```

### Claude Desktop

```json
{
  "mcpServers": {
    "google-sheets": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/service_account.json:/secrets/service_account.json:ro",
        "google-sheets-mcp"
      ]
    }
  }
}
```

> Docker Desktop должен быть запущен до старта Claude.

## Проверка

Smoke-тест проверяет, что сервер стартует, отдаёт все инструменты и корректно сообщает об отсутствии ключа (сам ключ не нужен):

```bash
python tests/smoke_test.py                                    # локально
python tests/smoke_test.py docker run -i --rm google-sheets-mcp  # в Docker
```

Тот же тест запускается в GitHub Actions на каждый push и pull request.

Интерактивно проверить инструменты можно через [MCP Inspector](https://github.com/modelcontextprotocol/inspector) (нужен Node.js):

```bash
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service_account.json \
  npx @modelcontextprotocol/inspector .venv/bin/python server.py
```

Примеры запросов к Claude:

- «Покажи, какие таблицы мне доступны»
- «Создай таблицу "Бюджет" и открой доступ на me@example.com»
- «Прочитай лист "Продажи" из https://docs.google.com/spreadsheets/d/... и посчитай итог»
- «Добавь в конец строку: 2026-10-01, Кофе, 350»

## Структура проекта

```
├── server.py              # MCP-сервер
├── requirements.txt       # зависимости
├── Dockerfile
├── tests/smoke_test.py    # smoke-тест по протоколу MCP
├── .github/workflows/     # CI: тесты на Python 3.10 и 3.13 + сборка Docker-образа
└── .env.example           # пример переменных окружения
```

## Лицензия

[MIT](LICENSE)
