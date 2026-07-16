import subprocess
import sys
import time

def execute_pipeline_step(script_name, description):
    print(f"\n⚡ [PIPELINE] {description} ({script_name})...")
    try:
        subprocess.run([sys.executable, script_name], check=True)
        return True
    except Exception as e:
        print(f"❌ Pipeline stepped encountered an error on {script_name}: {e}")
        return False

def run_core_agent_pipeline():
    print("============================================================")
    print("       🚀 RUNNING CORE AGENT PIPELINE (VIRGO RUN)          ")
    print("============================================================")
    
    # Step 1: Diagnostics
    if not execute_pipeline_step("virgo_diagnostics.py", "Analyzing System Health Metrics"):
        return
    time.sleep(1)
    
    # Step 2: Alert Evaluation
    if not execute_pipeline_step("virgo_alerts.py", "Evaluating Environmental Thresholds"):
        return
    time.sleep(1)
    
    # Step 3: Triage Fixes
    if not execute_pipeline_step("virgo_fixer.py", "Running Auto-Remediation Routines"):
        return
    time.sleep(1)
    
    # Step 4: Final verification pass
    if not execute_pipeline_step("virgo_alerts.py", "Executing Post-Fix Alert Validation Pass"):
        return
    
    print("\n🎯 Core pipeline run executed cleanly. Status: SECURE.")

if __name__ == "__main__":
    run_core_agent_pipeline()
    input("\n[PRESS ENTER TO RETURN]")