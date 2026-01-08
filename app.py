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
    try:
        resp = requests.get(GOOGLE_CSV_URL, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print("Error loading Google Sheet:", e)
        return [], []

    reader = csv.DictReader(StringIO(resp.text))
    raw_rows = list(reader)

    original_headers = reader.fieldnames or []
    header_map = {}
    columns = []

    for h in original_headers:
        clean = h.strip()
        header_map[h] = clean
        if clean not in columns:
            columns.append(clean)

    cleaned_rows = []
    for raw in raw_rows:
        row = {}
        for orig_key, value in raw.items():
            if orig_key is None:
                continue

            key = header_map[orig_key]
            if key in REMOVE_COLUMNS:
                continue

            new_key = RENAME_COLUMNS.get(key, key)
            row[new_key] = value.strip() if isinstance(value, str) else value

        # --- Split Comp Name / Specification ---
        full = row.get("Comp Name/Specification")
        if full:
            if " " in full:
                i = full.find(" ")
                row["Comp Name"] = full[:i]
                row["Specification"] = full[i + 1 :]
            else:
                row["Comp Name"] = full
                row["Specification"] = ""
            row.pop("Comp Name/Specification", None)

        cleaned_rows.append(row)

    new_columns = []
    for col in columns:
        if col in REMOVE_COLUMNS:
            continue

        renamed = RENAME_COLUMNS.get(col, col)
        if renamed == "Comp Name/Specification":
            new_columns.extend(["Comp Name", "Specification"])
        elif renamed not in new_columns:
            new_columns.append(renamed)

    return cleaned_rows, new_columns


@app.route("/", methods=["GET", "POST"])
def index():
    query = ""
    results = []
    columns = []

    # 🔹 GET — ничего не показываем
    if request.method == "GET":
        return render_template(
            "search.html",
            query=query,
            results=results,
            columns=columns,
            searched=False
        )

    # 🔹 POST — нажали Search
    query = request.form.get("q", "").strip()
    data, columns = load_inventory_from_google()

    # пустой поиск → показать всё
    if not query:
        results = data
    else:
        q = query.lower()
        for row in data:
            values = [str(v).lower() for v in row.values() if v]
            if any(q in v for v in values):
                results.append(row)

    return render_template(
        "search.html",
        query=query,
        results=results,
        columns=columns,
        searched=True
    )


if __name__ == "__main__":
    app.run(debug=True)
