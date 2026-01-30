from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import secrets
import json
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials


app = Flask(__name__)

# ✅ secret для сессий
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# ⏱ Auto logout after inactivity
SESSION_TIMEOUT = timedelta(minutes=15)

# ✅ пароль
PASSWORDS = {"admin": "Alfa7612155"}

# ✅ Google Sheet
SHEET_ID = "1fKdQMb_M6hwQKOjosAfLxfaXdLE56E_3zxPtN1A9S7I"
WORKSHEET_GID = 135237540

# --- НАСТРОЙКИ КОЛОНОК ----------------------------------------
REMOVE_COLUMNS = ["Windows 11 №"]

RENAME_COLUMNS = {
    "Windows 7 Comp Name": "Comp Name/Specification",
    "Maps Access 3DEYE ACCOUNTS Username": "3DEYE ACCOUNTS Username",
    "UVNC - Connect IP address": "IP address",
    "LAN Tempera Controller Password": "3DEYE ACCOUNTS Password",
    "Logmein - Connect Operator": "Logmein Connect Operator",
}

# Служебные колонки, которые не надо редактировать в форме
NON_EDITABLE = {"_row_id", "_display_no"}


# -------------------- SESSION TIMEOUT --------------------
@app.before_request
def session_timeout_check():
    # пропускаем login и static
    if request.endpoint in ("login", "static"):
        return

    if not session.get("logged_in"):
        return

    now = datetime.utcnow()
    last_activity = session.get("last_activity")

    if last_activity:
        try:
            last_dt = datetime.fromisoformat(last_activity)
            if now - last_dt > SESSION_TIMEOUT:
                session.clear()
                return redirect(url_for("login"))
        except Exception:
            # если вдруг формат сломался — просто сбросим
            session.clear()
            return redirect(url_for("login"))

    session["last_activity"] = now.isoformat()


# -------------------- Google client --------------------
def get_gspread_client():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("Missing env var GOOGLE_SERVICE_ACCOUNT_JSON")

    sa_info = json.loads(sa_json)

    # ✅ запись (не readonly)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def get_worksheet():
    client = get_gspread_client()
    sheet = client.open_by_key(SHEET_ID)
    return sheet.get_worksheet_by_id(WORKSHEET_GID)


def is_data_row_start(first_cell: str) -> bool:
    return (first_cell or "").strip().isdigit()


def parse_sheet_values(values):
    """
    values = worksheet.get_all_values()

    Возвращает:
    - cleaned_rows: список dict для отображения (с ключом _row_id)
    - display_columns: список колонок для таблицы (как ты отображаешь)
    - combined_headers: реальные комбинированные заголовки sheet (для update)
    - raw_row_indices: список row_index (1-based) для каждой строки raw_rows
    - data_start: индекс начала данных (0-based)
    """
    if not values or len(values) < 2:
        return [], [], [], [], None

    # 1) ищем где начинаются данные (первая колонка = число)
    data_start = None
    for i, row in enumerate(values):
        first = (row[0] if row else "").strip()
        if is_data_row_start(first):
            data_start = i
            break

    if data_start is None:
        header_rows = [values[0]]
        raw_rows = values[1:]
        raw_row_indices = list(range(2, 2 + len(raw_rows)))  # 1-based индексы
    else:
        header_rows = values[:data_start]
        raw_rows = values[data_start:]
        raw_row_indices = list(range(data_start + 1, data_start + 1 + len(raw_rows)))  # 1-based

    # 2) комбинируем заголовки
    max_cols = max((len(r) for r in header_rows), default=0)

    combined_headers = []
    for col_idx in range(max_cols):
        parts = []
        for hr in header_rows:
            cell = hr[col_idx].strip() if col_idx < len(hr) and hr[col_idx] else ""
            if cell:
                parts.append(cell)
        combined_headers.append(" ".join(parts).strip())

    # 3) columns как раньше (strip, порядок, без дублей)
    columns = []
    for h in combined_headers:
        clean = (h or "").strip()
        if clean and clean not in columns:
            columns.append(clean)

    # 4) собираем строки + ДОБАВЛЯЕМ _row_id = номер строки в Google Sheet (чтобы Edit был везде)
    cleaned_rows = []

    for row, sheet_row_idx in zip(raw_rows, raw_row_indices):
        clean_row = {}

        for idx, header in enumerate(combined_headers):
            if not header:
                continue

            key = header.strip()
            if key in REMOVE_COLUMNS:
                continue

            new_key = RENAME_COLUMNS.get(key, key)
            value = row[idx] if idx < len(row) else ""
            val = value.strip() if isinstance(value, str) else value

            if new_key not in clean_row:
                clean_row[new_key] = val

        # split Comp Name/Specification
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

        # ✅ ВСЕГДА: row_id = номер строки в sheet
        clean_row["_row_id"] = str(sheet_row_idx)

        # (необязательно) можно показать "№" если надо
        clean_row["_display_no"] = (row[0] if row else "").strip()

        # пропускаем пустые строки (кроме служебных)
        if any(v for k, v in clean_row.items() if k not in NON_EDITABLE):
            cleaned_rows.append(clean_row)

    # 5) display_columns как раньше
    display_columns = []
    for col in columns:
        if col in REMOVE_COLUMNS:
            continue

        renamed = RENAME_COLUMNS.get(col, col)

        if renamed == "Comp Name/Specification":
            for c in ("Comp Name", "Specification"):
                if c not in display_columns:
                    display_columns.append(c)
        else:
            if renamed and renamed not in display_columns:
                display_columns.append(renamed)

    return cleaned_rows, display_columns, combined_headers, raw_row_indices, data_start


def load_inventory():
    ws = get_worksheet()
    values = ws.get_all_values()
    return parse_sheet_values(values)


# ------------------ auth ------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = (request.form.get("password") or "").strip()
        for username, pwd in PASSWORDS.items():
            if password == pwd:
                session["logged_in"] = True
                session["user"] = username
                session["last_activity"] = datetime.utcnow().isoformat()
                return redirect(url_for("index"))
        error = "Incorrect password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------ main search page ------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    query = request.form.get("q", "").strip() if request.method == "POST" else ""

    if request.method == "GET":
        return render_template("search.html", query="", results=[], columns=[])

    data, columns, _combined_headers, _raw_row_indices, _data_start = load_inventory()

    if query:
        q = query.lower()
        results = []
        for row in data:
            values = [
                str(v).lower()
                for k, v in row.items()
                if v is not None and k not in NON_EDITABLE
            ]
            if any(q in v for v in values):
                results.append(row)
    else:
        results = data

    return render_template("search.html", query=query, results=results, columns=columns)


# ------------------ edit ------------------
@app.route("/edit/<row_id>", methods=["GET", "POST"])
def edit(row_id):
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    # row_id у нас = номер строки в Google Sheet
    try:
        sheet_row_index = int(row_id)
    except ValueError:
        flash("Invalid row id", "error")
        return redirect(url_for("index"))

    ws = get_worksheet()
    values = ws.get_all_values()
    rows, display_columns, combined_headers, _raw_row_indices, _data_start = parse_sheet_values(values)

    # текущая строка полностью
    current_row = ws.row_values(sheet_row_index)

    # Собираем sheet_dict: combined_header -> value
    sheet_dict = {}
    for idx, h in enumerate(combined_headers):
        if not h:
            continue
        sheet_dict[h] = current_row[idx] if idx < len(current_row) else ""

    # --- GET: показать форму ---
    if request.method == "GET":
        # применяем rename как при отображении
        temp = {}
        for h, v in sheet_dict.items():
            if h in REMOVE_COLUMNS:
                continue
            new_key = RENAME_COLUMNS.get(h, h)
            if new_key not in temp:
                temp[new_key] = v

        # split Comp Name/Specification
        full = (temp.get("Comp Name/Specification") or "").strip()
        if full:
            if " " in full:
                p = full.find(" ")
                temp["Comp Name"] = full[:p]
                temp["Specification"] = full[p + 1:]
            else:
                temp["Comp Name"] = full
                temp["Specification"] = ""
        temp.pop("Comp Name/Specification", None)

        form_data = {c: (temp.get(c, "") or "") for c in display_columns}
        return render_template("edit.html", row_id=row_id, columns=display_columns, data=form_data)

    # --- POST: сохранить ---
    form = request.form
    new_display = {c: (form.get(c) or "").strip() for c in display_columns}

    # собираем обратно Comp Name/Specification
    combined_comp = None
    if "Comp Name" in new_display or "Specification" in new_display:
        comp = (new_display.get("Comp Name") or "").strip()
        spec = (new_display.get("Specification") or "").strip()
        combined_comp = (comp + (" " + spec if spec else "")).strip()

    # Собираем обновления: col_index(1-based) -> value
    updates = {}

    for idx, sheet_header in enumerate(combined_headers):
        if not sheet_header:
            continue
        if sheet_header in REMOVE_COLUMNS:
            continue

        renamed = RENAME_COLUMNS.get(sheet_header, sheet_header)

        # Comp Name/Specification пишем в оригинальную колонку
        if renamed == "Comp Name/Specification":
            if combined_comp is not None:
                updates[idx + 1] = combined_comp
            continue

        # обычные поля
        if renamed in new_display:
            updates[idx + 1] = new_display[renamed]

    try:
        cells = []
        for col_idx_1based, val in updates.items():
            cells.append(gspread.Cell(sheet_row_index, col_idx_1based, val))

        if cells:
            ws.update_cells(cells, value_input_option="USER_ENTERED")

        flash("Saved!", "success")
    except Exception as e:
        flash(f"Save error: {e}", "error")

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
