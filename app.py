from flask import Flask, render_template, request, redirect, url_for, session
import os
import secrets
import json

import gspread
from google.oauth2.service_account import Credentials


app = Flask(__name__)

# ✅ Секретный ключ для сессий:
# Render: добавь Environment Variable: FLASK_SECRET_KEY = (любой длинный random)
# Локально: если переменной нет — создаст временный ключ (при рестарте сменится)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# ✅ Один пароль (только admin)
PASSWORDS = {
    "admin": "Alfa7462111",
}

# --- Google Sheet settings ---
SHEET_ID = "1fKdQMb_M6hwQKOjosAfLxfaXdLE56E_3zxPtN1A9S7I"
WORKSHEET_GID = 135237540  # твой gid

# --- НАСТРОЙКИ КОЛОНОК ----------------------------------------

REMOVE_COLUMNS = [
    "Windows 11 №",
]

RENAME_COLUMNS = {
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
        cols.append(col_name)

    return cols


def load_inventory_from_google():
    """
    Читает данные из Google Sheets через Service Account.
    Service account JSON лежит в переменной окружения GOOGLE_SERVICE_ACCOUNT_JSON
    """
    try:
        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not sa_json:
            raise RuntimeError("Missing env var GOOGLE_SERVICE_ACCOUNT_JSON")

        sa_info = json.loads(sa_json)

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)

        sheet = client.open_by_key(SHEET_ID)
        worksheet = sheet.get_worksheet_by_id(WORKSHEET_GID)

        # список словарей (ключи = заголовки)
        raw_rows = worksheet.get_all_records()
        # заголовки в порядке как в таблице
        original_headers = worksheet.row_values(1)

    except Exception as e:
        print("❌ Google Sheets error:", e)
        return [], []

    # 1) Заголовки (в порядке как в Google Sheets)
    columns = []
    header_map = {}

    for h in original_headers:
        if h is None:
            continue
        clean = str(h).strip()
        header_map[h] = clean
        if clean and clean not in columns:
            columns.append(clean)

    # 2) Чистим строки: удаляем/переименовываем + split Comp Name/Specification
    cleaned_rows = []
    for raw in raw_rows:
        clean_row = {}

        for key, v in raw.items():
            if key is None:
                continue

            key_clean = str(key).strip()

            if key_clean in REMOVE_COLUMNS:
                continue

            new_key = RENAME_COLUMNS.get(key_clean, key_clean)
            val = v.strip() if isinstance(v, str) else v
            clean_row[new_key] = val

        # split "Comp Name/Specification" -> "Comp Name" + "Specification"
        full = clean_row.get("Comp Name/Specification")
        if full:
            full = full.strip()
            if " " in full:
                first_space = full.find(" ")
                comp_name = full[:first_space]
                spec = full[first_space + 1:]
            else:
                comp_name = full
                spec = ""

            clean_row["Comp Name"] = comp_name
            clean_row["Specification"] = spec
            clean_row.pop("Comp Name/Specification", None)

        cleaned_rows.append(clean_row)

    # 3) Обновляем список колонок (без удалённых, с учётом переименования)
    new_columns = []
    for col in columns:
        if col in REMOVE_COLUMNS:
            continue

        renamed = RENAME_COLUMNS.get(col, col)

        if renamed == "Comp Name/Specification":
            for c in ("Comp Name", "Specification"):
                if c not in new_columns:
                    new_columns.append(c)
            continue

        if renamed not in new_columns:
            new_columns.append(renamed)

    print(f"✅ Loaded {len(cleaned_rows)} rows")
    return cleaned_rows, new_columns


# ------------------ ЛОГИН ТОЛЬКО ПО ПАРОЛЮ ------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = (request.form.get("password") or "").strip()

        for username, pwd in PASSWORDS.items():
            if password == pwd:
                session["logged_in"] = True
                session["user"] = username
                return redirect(url_for("index"))

        error = "Incorrect password"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------ ОСНОВНАЯ СТРАНИЦА ПОИСКА ------------------

@app.route("/", methods=["GET", "POST"])
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    query = request.form.get("q", "").strip() if request.method == "POST" else ""

    results = []
    columns = []

    if request.method == "GET":
        return render_template("search.html", query=query, results=results, columns=columns)

    data, columns = load_inventory_from_google()

    if query:
        q = query.lower()
        for row in data:
            values = [str(v).lower() for v in row.values() if v is not None]
            if any(q in v for v in values):
                results.append(row)
    else:
        results = data

    return render_template("search.html", query=query, results=results, columns=columns)


if __name__ == "__main__":
    app.run()
