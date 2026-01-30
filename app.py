from flask import Flask, render_template, request, redirect, url_for, session
import os
import secrets
import json
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ✅ Секретный ключ для сессий:
# Render: Environment Variable -> FLASK_SECRET_KEY = (любой длинный random)
# Local: если переменной нет — создаст временный ключ (при рестарте сменится)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# ✅ Один пароль (только admin)
PASSWORDS = {
    "admin": "Alfa7612155",
}

# ✅ Google Sheet
SHEET_ID = "1fKdQMb_M6hwQKOjosAfLxfaXdLE56E_3zxPtN1A9S7I"
WORKSHEET_GID = 135237540

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


def load_inventory_from_google():
    """
    Читает данные из Google Sheets через Service Account.

    ВАЖНО: у тебя заголовки в 2-3 строки (группы + подзаголовки),
    поэтому мы:
    1) находим строку, где начинаются данные (первая колонка = число)
    2) берём все строки выше как "header rows"
    3) склеиваем заголовки по колонкам: "Windows 7" + "Comp Name" -> "Windows 7 Comp Name"
    4) дальше применяем REMOVE / RENAME и split Comp Name/Specification.
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

        values = worksheet.get_all_values()
        if not values or len(values) < 2:
            return [], []

    except Exception as e:
        print("❌ Google Sheets error:", e)
        return [], []

    # --------- 1) Находим, где начинаются данные (там где первая ячейка = число) ----------
    data_start = None
    for i, row in enumerate(values):
        first = (row[0] if row else "").strip()
        if first.isdigit():
            data_start = i
            break

    # если не нашли — считаем, что первая строка заголовок, дальше данные
    if data_start is None:
        header_rows = [values[0]]
        raw_rows = values[1:]
    else:
        header_rows = values[:data_start]   # 2-3 строки заголовков
        raw_rows = values[data_start:]      # данные

    # --------- 2) Склеиваем заголовки из нескольких строк ----------
    max_cols = max((len(r) for r in header_rows), default=0)

    combined_headers = []
    for col_idx in range(max_cols):
        parts = []
        for hr in header_rows:
            cell = hr[col_idx].strip() if col_idx < len(hr) and hr[col_idx] else ""
            if cell:
                parts.append(cell)
        combined = " ".join(parts).strip()
        combined_headers.append(combined)

    # --------- 3) Делаем columns/header_map как в твоём “верхнем” коде ----------
    columns = []
    header_map = {}
    for h in combined_headers:
        if h is None:
            continue
        clean = h.strip()
        header_map[h] = clean
        if clean and clean not in columns:
            columns.append(clean)

    # --------- 4) Собираем строки данных ----------
    cleaned_rows = []
    for row in raw_rows:
        clean_row = {}

        # превращаем ряд в dict по нашим комбинированным headers
        for idx, header in enumerate(combined_headers):
            if not header:
                continue

            key = header.strip()
            if key in REMOVE_COLUMNS:
                continue

            new_key = RENAME_COLUMNS.get(key, key)
            value = row[idx] if idx < len(row) else ""
            val = value.strip() if isinstance(value, str) else value

            # как DictReader при дублях: не перезаписываем
            if new_key not in clean_row:
                clean_row[new_key] = val

        # --------- разделяем Comp Name/Specification на две колонки ---------
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
        # --------------------------------------------------------------------

        # пропускаем совсем пустые строки (если бывают)
        if any(v for v in clean_row.values()):
            cleaned_rows.append(clean_row)

    # --------- 5) Финальные колонки (как в верхнем коде) ----------
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

        if renamed and renamed not in new_columns:
            new_columns.append(renamed)

    print(f"✅ Loaded {len(cleaned_rows)} rows")
    print("✅ Columns:", new_columns)

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
