from flask import Flask, render_template, request, redirect, url_for, session
import os
import secrets
import json
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ✅ Секретный ключ для сессий:
# На Render добавь Environment Variable: FLASK_SECRET_KEY = (любой длинный random)
# Локально: если переменной нет — создаст временный ключ (при рестарте сменится)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# ✅ Один пароль (только admin)
PASSWORDS = {
    "admin": "Alfa7462111",
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
    JSON сервис-аккаунта хранится в env GOOGLE_SERVICE_ACCOUNT_JSON.
    Используем get_all_values(), чтобы не падать на дубликатах заголовков.
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

        raw_headers = values[0]
        raw_rows = values[1:]

    except Exception as e:
        print("❌ Google Sheets error:", e)
        return [], []

    # ---------- ЧИСТИМ ЗАГОЛОВКИ (убираем пустые и дубликаты) ----------
    headers = []
    header_map = {}  # idx -> header_name

    for idx, h in enumerate(raw_headers):
        clean = (h or "").strip()

        if not clean:
            clean = f"Column_{idx}"

        original = clean
        counter = 1
        while clean in headers:
            clean = f"{original}_{counter}"
            counter += 1

        header_map[idx] = clean
        headers.append(clean)

    # ---------- СОБИРАЕМ СТРОКИ ----------
    cleaned_rows = []

    for row in raw_rows:
        clean_row = {}

        for idx, value in enumerate(row):
            key = header_map.get(idx)
            if not key:
                continue

            if key in REMOVE_COLUMNS:
                continue

            new_key = RENAME_COLUMNS.get(key, key)
            clean_row[new_key] = value.strip() if isinstance(value, str) else value

        # ---- Comp Name / Specification ----
        full = clean_row.get("Comp Name/Specification")
        if full:
            full = full.strip()
            if " " in full:
                p = full.find(" ")
                clean_row["Comp Name"] = full[:p]
                clean_row["Specification"] = full[p + 1:]
            else:
                clean_row["Comp Name"] = full
                clean_row["Specification"] = ""

            clean_row.pop("Comp Name/Specification", None)

        cleaned_rows.append(clean_row)

    # ---------- КОЛОНКИ ----------
    columns = []
    for h in headers:
        if h in REMOVE_COLUMNS:
            continue

        renamed = RENAME_COLUMNS.get(h, h)

        if renamed == "Comp Name/Specification":
            for c in ("Comp Name", "Specification"):
                if c not in columns:
                    columns.append(c)
        elif renamed not in columns:
            columns.append(renamed)

    print(f"✅ Loaded {len(cleaned_rows)} rows")
    print("✅ Columns:", columns)

    return cleaned_rows, columns


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

    # query берём только при POST; при GET будет пусто и ничего не покажется
    query = request.form.get("q", "").strip() if request.method == "POST" else ""

    results = []
    columns = []

    # GET: ничего не показываем
    if request.method == "GET":
        return render_template("search.html", query=query, results=results, columns=columns)

    # POST: нажали Search -> грузим данные
    data, columns = load_inventory_from_google()

    if query:
        q = query.lower()
        for row in data:
            values = [str(v).lower() for v in row.values() if v is not None]
            if any(q in v for v in values):
                results.append(row)
    else:
        # Search с пустым полем -> показываем весь список
        results = data

    return render_template("search.html", query=query, results=results, columns=columns)


if __name__ == "__main__":
    # локально можно debug=True, на Render не нужно
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
