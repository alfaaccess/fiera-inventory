from flask import Flask, render_template, request
import csv
import requests
from io import StringIO

app = Flask(__name__)

GOOGLE_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1fKdQMb_M6hwQKOjosAfLxfaXdLE56E_3zxPtN1A9S7I"
    "/gviz/tq?tqx=out:csv&gid=135237540"
)

# --- НАСТРОЙКИ КОЛОНОК ----------------------------------------

# Какие колонки полностью убрать (из вывода и из данных)
REMOVE_COLUMNS = [
    "Windows 11 №",          # уже удаляем
    # "LAN Tempera Controller Password",  # ← можешь добавить сюда ещё
]

# Переименование колонок: "старое имя" -> "новое имя"
RENAME_COLUMNS = {
    # Windows 7 Comp Name → временное объединённое поле
    "Windows 7 Comp Name": "Comp Name/Specification",
    "Maps Access 3DEYE ACCOUNTS Username": "3DEYE ACCOUNTS Username",
    "UVNC - Connect IP address": "IP address",
    "LAN Tempera Controller Password": "3DEYE ACCOUNTS Password",
    "Logmein - Connect Operator": "Logmein Connect Operator",
}


def move_column(columns, col_name, *, before=None, after=None):
    """
    Вспомогательная функция: переместить колонку col_name
    перед before или после after.
    Если before/after не найдены, порядок не меняется.
    """
    if col_name not in columns:
        return columns

    cols = columns.copy()
    cols.remove(col_name)

    if before and before in cols:
        idx = cols.index(before)
        cols.insert(idx, col_name)
    elif after and after in cols:
        idx = cols.index(after) + 1
        cols.insert(idx, col_name)
    else:
        # если не нашли куда вставить – вернём в конец
        cols.append(col_name)

    return cols


def load_inventory_from_google():
    """
    Load the Google Sheet (CSV) into a list of dicts
    and return (rows, columns).
    Column names are cleaned with strip(), порядок сохраняем.
    """
    try:
        resp = requests.get(GOOGLE_CSV_URL, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print("Error loading Google Sheet:", e)
        return [], []

    reader = csv.DictReader(StringIO(resp.text))
    raw_rows = list(reader)

    # 1. Берём исходные заголовки (в порядке, как в Google Sheets)
    original_headers = reader.fieldnames or []

    columns = []
    header_map = {}

    for h in original_headers:
        if h is None:
            continue
        clean = h.strip()
        header_map[h] = clean
        if clean not in columns:
            columns.append(clean)

    # 2. Чистим строки, при этом удаляем и переименовываем колонки
    cleaned_rows = []
    for raw in raw_rows:
        clean_row = {}
        for orig_key, v in raw.items():
            if orig_key is None:
                continue

            key = header_map[orig_key]  # очищенное имя заголовка

            if key in REMOVE_COLUMNS:
                # пропускаем ненужную колонку
                continue

            # переименование, если есть в словаре RENAME_COLUMNS
            new_key = RENAME_COLUMNS.get(key, key)

            val = v.strip() if isinstance(v, str) else v
            clean_row[new_key] = val

        # --------- разделяем Comp Name/Specification на две колонки ---------
        full = clean_row.get("Comp Name/Specification")
        if full:
            full = full.strip()
            if " " in full:
                first_space = full.find(" ")
                comp_name = full[:first_space]
                spec = full[first_space + 1 :]
            else:
                comp_name = full
                spec = ""

            clean_row["Comp Name"] = comp_name
            clean_row["Specification"] = spec

            # старое объединённое поле больше не нужно
            clean_row.pop("Comp Name/Specification", None)
        # --------------------------------------------------------------------

        cleaned_rows.append(clean_row)

    # 3. Обновляем список колонок (без удалённых, с учётом переименования)
    new_columns = []
    for col in columns:
        if col in REMOVE_COLUMNS:
            continue

        # применяем переименование
        renamed = RENAME_COLUMNS.get(col, col)

        # вместо "Comp Name/Specification" добавляем две новые колонки
        if renamed == "Comp Name/Specification":
            for c in ("Comp Name", "Specification"):
                if c not in new_columns:
                    new_columns.append(c)
            continue

        if renamed not in new_columns:
            new_columns.append(renamed)

    # при желании можно двигать колонки:
    # new_columns = move_column(new_columns, "Specification", after="Comp Name")

    print(f"Loaded {len(cleaned_rows)} rows")
    print("Columns:", new_columns)

    return cleaned_rows, new_columns


@app.route("/", methods=["GET", "POST"])
def index():
    query = request.form.get("q", "").strip()
    results = []
    columns = []

    if query:
        q = query.lower()
        data, columns = load_inventory_from_google()

        for row in data:
            # full-text search across ALL values in the row
            values = [str(v).lower() for v in row.values() if v is not None]
            if any(q in v for v in values):
                results.append(row)

    return render_template("search.html", query=query, results=results, columns=columns)


if __name__ == "__main__":
    app.run(debug=True)
