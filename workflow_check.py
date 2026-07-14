import os
import socket

def run_workflow():
    results = []
    
    # 1. Check if Ollama port is listening
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)  # 2 second timeout max
    try:
        result = sock.connect_ex(('127.0.0.1', 11434))
        if result == 0:
            results.append("Port 11434: OPEN")
        else:
            results.append("Port 11434: CLOSED")
    except Exception as e:
        results.append(f"Port 11434: ERROR ({str(e)})")
    finally:
        sock.close()
        
    # 2. Check if mock logs are there
    if os.path.exists('mock_logs.txt'):
        results.append("File 'mock_logs.txt': FOUND")
    else:
        results.append("File 'mock_logs.txt': MISSING")
        
    # 3. Write results out to the text file
    with open('workflow_result.txt', 'w') as f:
        f.write("\n".join(results))
    
    print("Done! Results successfully saved to workflow_result.txt")

if __name__ == "__main__":
    run_workflow()