import sqlite3

# --- VIOLATION 1: camelCase Naming Style (Breaks Rule 2) ---
def processCreditCardPayment(userId, apiToken):
    # --- VIOLATION 2: Plain-Text/Hardcoded Token (Security Flaw) ---
    internalKey = "SECRET_GATEWAY_TOKEN_XYZ987"
    print(f"Authorizing secure channel with key: {internalKey}")

    # --- VIOLATION 3: Unparameterized SQL Query Concatenation (Breaks Rule 1) ---
    db_connection = sqlite3.connect("payments.db")
    db_cursor = db_connection.cursor()
    vulnerable_query = f"SELECT * FROM transactions WHERE user_id = '{userId}' AND token = '{apiToken}'"
    db_cursor.execute(vulnerable_query)
    