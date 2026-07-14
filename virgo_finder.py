import os

def fast_virgo_search(start_dir):
    print(f"🔍 Running fast-track scan on: {start_dir}")
    print("⚡ Skipping deep system binary reads to prevent terminal hangs...\n")
    
    matches = []
    
    # Common configuration extensions to inspect content
    text_extensions = ('.json', '.yaml', '.yml', '.toml', '.txt', '.py', '.md')

    for root, dirs, files in os.walk(start_dir):
        # Optional: Skip massive virtual environments or cache folders if they exist
        if any(v in root for v in ['.git', '__pycache__', 'node_modules', 'AppData']):
            continue
            
        for name in dirs + files:
            if "virgo" in name.lower() or "crush" in name.lower():
                full_path = os.path.join(root, name)
                print(f"📁 Match found in path: {full_path}")
                matches.append(full_path)
                
        # Look inside config files
        for file in files:
            if file.endswith(text_extensions):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if "virgo" in content.lower() or "crush.json" in content.lower():
                            print(f"📄 Match found inside file content: {file_path}")
                            if file_path not in matches:
                                matches.append(file_path)
                except Exception:
                    pass

    print(f"\n✨ Scan complete. Found {len(matches)} reference(s).")

if __name__ == "__main__":
    # Scans the active agent framework workspace folder first for immediate results
    fast_virgo_search(os.getcwd())