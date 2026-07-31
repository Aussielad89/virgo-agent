import subprocess
import json
import psutil
import ollama

# Choose your local model
MODEL_NAME = "phi4-mini-reasoning:3.8b"

# --- TOOL 1: Hardware Diagnostics ---
def get_hardware_stats():
    """Gather current CPU, RAM, and universal GPU metrics via PowerShell."""
    stats = {
        "cpu_usage_percent": psutil.cpu_percent(interval=1),
        "ram": {
            "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
            "percent_used": psutil.virtual_memory().percent
        }
    }
    
    # Query all GPU display adapters via PowerShell CIM (Intel, AMD, NVIDIA)
    try:
        ps_gpu_cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, VideoProcessor | ConvertTo-Json"
        gpu_result = subprocess.check_output(["powershell", "-Command", ps_gpu_cmd], text=True).strip()
        if gpu_result:
            gpu_data = json.loads(gpu_result)
            if isinstance(gpu_data, dict):
                gpu_data = [gpu_data]
            stats["gpus_detected"] = [
                {
                    "name": g.get("Name"),
                    "driver_version": g.get("DriverVersion"),
                    "processor": g.get("VideoProcessor")
                }
                for g in gpu_data
            ]
    except Exception as e:
        stats["gpus_detected"] = f"Unable to query GPU info: {e}"

    return stats

# --- TOOL 2: System Event Log Checker ---
def get_system_errors(limit=5):
    """Retrieve recent Error events from Windows System Log via PowerShell."""
    try:
        ps_cmd = f"Get-WinEvent -FilterHashtable @{{LogName='System'; Level=2}} -MaxEvents {limit} -ErrorAction SilentlyContinue | Select-Object TimeCreated, Message | ConvertTo-Json"
        result = subprocess.check_output(["powershell", "-Command", ps_cmd], text=True).strip()
        if not result:
            return "No recent system errors found in event log."
        logs = json.loads(result)
        return [{"time": l.get("TimeCreated"), "message": str(l.get("Message", "")).strip()[:200]} for l in (logs if isinstance(logs, list) else [logs])]
    except Exception as e:
        return f"Error querying system event logs: {e}"
# --- MAIN AGENT LOOP ---
def run_diagnostics(model_name=MODEL_NAME):
    """
    Runs hardware and log checks, passes them to Ollama,
    and returns the string report while immediately clearing model VRAM/RAM.
    """
    print("🔍 [1/3] Gathering hardware metrics...")
    hw_data = get_hardware_stats()
    
    print("📋 [2/3] Checking system logs for critical errors...")
    log_data = get_system_errors()

    print("🧠 [3/3] Passing diagnostics to local AI model for analysis...\n")

    prompt = f"""
System Diagnostic Context:
--- HARDWARE METRICS ---
{json.dumps(hw_data, indent=2)}

--- RECENT SYSTEM LOG ERRORS ---
{json.dumps(log_data, indent=2)}

Task:
Analyze the hardware state and log errors above.
1. Summary: Give a brief assessment of system health (CPU, RAM, GPU status).
2. Warnings/Issues: Highlight any abnormal resource usage or critical log entries.
3. Action Plan: Provide specific CLI/Powershell commands or troubleshooting steps to resolve any detected issues.
"""

    response = ollama.chat(
        model=model_name,
        messages=[
            {"role": "system", "content": "You are an expert system administrator and diagnostic technician."},
            {"role": "user", "content": prompt}
        ],
        keep_alive="0s"  # Automatically releases memory from RAM immediately after response
    )

    return response['message']['content']

if __name__ == "__main__":
    report = run_diagnostics()
    print("================ SYSTEM DIAGNOSTIC REPORT ================")
    print(report)