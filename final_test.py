import sqlite3

# --- VIOLATION 1: camelCase Naming Convention (Breaks Rule 2) ---
def userAuthenticationStep():
    myBadVariable = "Testing scaling"

    # --- VIOLATION 2: Direct string formatting inside SQL (Breaks Rule 1) ---
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM accounts WHERE username = '{myBadVariable}'"
    cursor.execute(query)