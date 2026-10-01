"""MCP-сервер для работы с Google Sheets.

Авторизация через сервисный аккаунт Google:
    GOOGLE_SERVICE_ACCOUNT_FILE — путь к JSON-ключу сервисного аккаунта.

Запуск (stdio):
    python server.py
"""

from __future__ import annotations

import functools
import os
from functools import lru_cache
from typing import Any, Callable

import gspread
from gspread.utils import ValueInputOption
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("google-sheets")


def tool(fn: Callable) -> Callable:
    """Регистрирует MCP-инструмент и превращает ошибки в понятные сообщения.

    MCP SDK показывает модели текст только у ToolError, остальные исключения
    скрываются за «Error executing tool», поэтому конвертируем их здесь.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except gspread.SpreadsheetNotFound:
            raise ToolError(
                "Таблица не найдена. Проверьте ID/ссылку и что таблица открыта "
                "для email сервисного аккаунта."
            )
        except gspread.WorksheetNotFound as e:
            raise ToolError(f"Лист не найден: {e}")
        except gspread.exceptions.APIError as e:
            raise ToolError(f"Ошибка Google API: {e}")
        except PermissionError as e:
            # gspread.open_by_key превращает любой 403 в голый PermissionError,
            # а исходная ошибка API лежит в __cause__.
            detail = f": {e.__cause__}" if e.__cause__ else ""
            raise ToolError(
                "Нет доступа (403). Проверьте, что в Google Cloud включены Sheets API "
                "и Drive API, а таблица открыта для email сервисного аккаунта" + detail
            )
        except (ValueError, RuntimeError) as e:
            raise ToolError(str(e))

    return mcp.tool()(wrapper)


@lru_cache(maxsize=1)
def get_client() -> gspread.Client:
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not path:
        raise ToolError(
            "Не задана переменная окружения GOOGLE_SERVICE_ACCOUNT_FILE "
            "(путь к JSON-ключу сервисного аккаунта)."
        )
    if not os.path.isfile(path):
        raise ToolError(f"Файл ключа не найден: {path}")
    return gspread.service_account(filename=path)


def open_spreadsheet(spreadsheet: str) -> gspread.Spreadsheet:
    """Открывает таблицу по ID или полной ссылке."""
    client = get_client()
    if spreadsheet.startswith("http"):
        return client.open_by_url(spreadsheet)
    return client.open_by_key(spreadsheet)


def get_worksheet(sh: gspread.Spreadsheet, sheet: str | None) -> gspread.Worksheet:
    return sh.worksheet(sheet) if sheet else sh.sheet1


def worksheet_info(ws: gspread.Worksheet) -> dict[str, Any]:
    return {
        "title": ws.title,
        "sheet_id": ws.id,
        "index": ws.index,
        "rows": ws.row_count,
        "cols": ws.col_count,
    }


# ---------------------------------------------------------------- таблицы


@tool
def list_spreadsheets(query: str | None = None) -> list[dict[str, str]]:
    """Список таблиц, доступных сервисному аккаунту.

    Args:
        query: необязательный фильтр — подстрока в названии таблицы.
    """
    files = get_client().list_spreadsheet_files()
    result = [
        {
            "id": f["id"],
            "name": f["name"],
            "url": f"https://docs.google.com/spreadsheets/d/{f['id']}",
        }
        for f in files
    ]
    if query:
        result = [f for f in result if query.lower() in f["name"].lower()]
    return result


@tool
def get_spreadsheet_info(spreadsheet: str) -> dict[str, Any]:
    """Информация о таблице: название, ссылка и список листов с размерами.

    Args:
        spreadsheet: ID таблицы или её полная ссылка.
    """
    sh = open_spreadsheet(spreadsheet)
    return {
        "id": sh.id,
        "title": sh.title,
        "url": sh.url,
        "sheets": [worksheet_info(ws) for ws in sh.worksheets()],
    }


@tool
def create_spreadsheet(title: str, share_with: str | None = None) -> dict[str, str]:
    """Создаёт новую таблицу.

    Таблица принадлежит сервисному аккаунту, поэтому укажите share_with,
    чтобы она появилась у вас в Google Drive.

    Args:
        title: название таблицы.
        share_with: email, которому выдать права редактора (необязательно).
    """
    try:
        sh = get_client().create(title)
    except gspread.exceptions.APIError as e:
        if "storageQuotaExceeded" in str(e) or "storage quota" in str(e):
            raise ToolError(
                "Сервисный аккаунт не может создавать таблицы: у него нет места на "
                "Google Drive (у новых сервисных аккаунтов квота равна 0). Создайте "
                "таблицу вручную и откройте к ней доступ для email сервисного аккаунта."
            )
        raise
    if share_with:
        sh.share(share_with, perm_type="user", role="writer")
    return {"id": sh.id, "title": sh.title, "url": sh.url}


@tool
def share_spreadsheet(
    spreadsheet: str, email: str, role: str = "writer", notify: bool = True
) -> str:
    """Открывает доступ к таблице для пользователя.

    Args:
        spreadsheet: ID таблицы или ссылка.
        email: email пользователя.
        role: "reader", "commenter" или "writer".
        notify: отправить ли уведомление на почту.
    """
    if role not in ("reader", "commenter", "writer"):
        raise ValueError("role должен быть reader, commenter или writer")
    sh = open_spreadsheet(spreadsheet)
    sh.share(email, perm_type="user", role=role, notify=notify)
    return f"Доступ «{role}» выдан {email}"


# ---------------------------------------------------------------- листы


@tool
def add_sheet(spreadsheet: str, title: str, rows: int = 1000, cols: int = 26) -> dict[str, Any]:
    """Добавляет новый лист в таблицу.

    Args:
        spreadsheet: ID таблицы или ссылка.
        title: название листа.
        rows: количество строк.
        cols: количество столбцов.
    """
    ws = open_spreadsheet(spreadsheet).add_worksheet(title=title, rows=rows, cols=cols)
    return worksheet_info(ws)


@tool
def rename_sheet(spreadsheet: str, sheet: str, new_title: str) -> str:
    """Переименовывает лист.

    Args:
        spreadsheet: ID таблицы или ссылка.
        sheet: текущее название листа.
        new_title: новое название.
    """
    ws = open_spreadsheet(spreadsheet).worksheet(sheet)
    ws.update_title(new_title)
    return f"Лист «{sheet}» переименован в «{new_title}»"


@tool
def delete_sheet(spreadsheet: str, sheet: str) -> str:
    """Удаляет лист из таблицы (без возможности восстановления).

    Args:
        spreadsheet: ID таблицы или ссылка.
        sheet: название листа.
    """
    sh = open_spreadsheet(spreadsheet)
    sh.del_worksheet(sh.worksheet(sheet))
    return f"Лист «{sheet}» удалён"


# ---------------------------------------------------------------- данные


@tool
def read_range(
    spreadsheet: str,
    range: str | None = None,
    sheet: str | None = None,
    formulas: bool = False,
) -> list[list[Any]]:
    """Читает значения из листа.

    Args:
        spreadsheet: ID таблицы или ссылка.
        range: диапазон в A1-нотации, например "A1:D10". Если не указан — весь лист.
        sheet: название листа (по умолчанию первый лист).
        formulas: вернуть формулы вместо вычисленных значений.
    """
    ws = get_worksheet(open_spreadsheet(spreadsheet), sheet)
    render = (
        gspread.utils.ValueRenderOption.formula
        if formulas
        else gspread.utils.ValueRenderOption.formatted
    )
    if range:
        values = ws.get(range, value_render_option=render)
    else:
        values = ws.get_all_values(value_render_option=render)
    # gspread возвращает [[]] для пустого листа
    return values if any(values) else []


@tool
def read_records(spreadsheet: str, sheet: str | None = None) -> list[dict[str, Any]]:
    """Читает лист как список записей: первая строка — заголовки столбцов.

    Args:
        spreadsheet: ID таблицы или ссылка.
        sheet: название листа (по умолчанию первый лист).
    """
    ws = get_worksheet(open_spreadsheet(spreadsheet), sheet)
    return ws.get_all_records()


@tool
def write_range(
    spreadsheet: str,
    range: str,
    values: list[list[Any]],
    sheet: str | None = None,
) -> dict[str, Any]:
    """Записывает значения в диапазон (перезаписывает существующие).

    Значения интерпретируются как ввод пользователя: строки вида "=SUM(A1:A3)"
    станут формулами, "1.5" — числом.

    Args:
        spreadsheet: ID таблицы или ссылка.
        range: начальная ячейка или диапазон в A1-нотации, например "A1" или "B2:D4".
        values: двумерный массив значений (список строк).
        sheet: название листа (по умолчанию первый лист).
    """
    ws = get_worksheet(open_spreadsheet(spreadsheet), sheet)
    resp = ws.update(values, range, value_input_option=ValueInputOption.user_entered)
    return {
        "updated_range": resp.get("updatedRange"),
        "updated_cells": resp.get("updatedCells"),
    }


@tool
def append_rows(
    spreadsheet: str, values: list[list[Any]], sheet: str | None = None
) -> dict[str, Any]:
    """Добавляет строки в конец данных на листе.

    Args:
        spreadsheet: ID таблицы или ссылка.
        values: двумерный массив значений (список строк).
        sheet: название листа (по умолчанию первый лист).
    """
    ws = get_worksheet(open_spreadsheet(spreadsheet), sheet)
    resp = ws.append_rows(values, value_input_option=ValueInputOption.user_entered)
    updates = resp.get("updates", {})
    return {
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows"),
    }


@tool
def clear_range(spreadsheet: str, range: str | None = None, sheet: str | None = None) -> str:
    """Очищает значения в диапазоне (форматирование сохраняется).

    Args:
        spreadsheet: ID таблицы или ссылка.
        range: диапазон в A1-нотации. Если не указан — очищается весь лист.
        sheet: название листа (по умолчанию первый лист).
    """
    ws = get_worksheet(open_spreadsheet(spreadsheet), sheet)
    if range:
        ws.batch_clear([range])
        return f"Диапазон {range} на листе «{ws.title}» очищен"
    ws.clear()
    return f"Лист «{ws.title}» очищен"


@tool
def find_cells(
    spreadsheet: str,
    query: str,
    sheet: str | None = None,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Ищет ячейки, содержащие текст.

    Args:
        spreadsheet: ID таблицы или ссылка.
        query: искомая подстрока.
        sheet: название листа (по умолчанию — все листы таблицы).
        case_sensitive: учитывать регистр.
    """
    sh = open_spreadsheet(spreadsheet)
    sheets = [sh.worksheet(sheet)] if sheet else sh.worksheets()
    needle = query if case_sensitive else query.lower()
    found = []
    for ws in sheets:
        for r, row in enumerate(ws.get_all_values(), start=1):
            for c, value in enumerate(row, start=1):
                hay = value if case_sensitive else value.lower()
                if needle in hay:
                    found.append(
                        {
                            "sheet": ws.title,
                            "cell": gspread.utils.rowcol_to_a1(r, c),
                            "value": value,
                        }
                    )
    return found


if __name__ == "__main__":
    mcp.run()
