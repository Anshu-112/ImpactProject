import sqlite3

# --- VIOLATION 1: Direct f-string formatting inside a SQL execution block ---
# Rule 1 states: Never use direct string formatting to avoid SQL injection risks.
def bad_login(user_input_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Deliberate vulnerability created here:
    query = f"SELECT * FROM users WHERE id = '{user_input_id}'"
    cursor.execute(query)
    return cursor.fetchall()


# --- VIOLATION 2: CamelCase variable formatting usage profile ---
# Rule 2 states: All Python function names and variables must use snake_case.
def process_data():
    # Deliberate style violation created here:
    myBadCamelCaseVariable = "This breaks rule number 2"
    print(myBadCamelCaseVariable)
    #new line 