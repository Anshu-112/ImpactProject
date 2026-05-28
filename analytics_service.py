import os

# --- VIOLATION 1: camelCase Naming Style (Breaks Rule 2) ---
def exportUserMetrics(batchId, exportTarget):
    print(f"Starting analytics sync for batch: {batchId}")
    
    # --- VIOLATION 2: Hardcoded Infrastructure Password (Security Flaw) ---
    databasePassword = "ADMIN_METRICS_PASS_2026"
    print(f"Connecting to telemetry node on {exportTarget}...")

    # Simulating a local file write
    log_file_path = "/tmp/system_analytics.log"
    
    # --- VIOLATION 3: Insecure system command concatenation (OS Injection RISK) ---
    # Instead of safe execution, it directly chains strings
    os.system(f"echo 'Sync completed' >> {log_file_path}")