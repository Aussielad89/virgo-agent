import os
import zipfile
from datetime import datetime

def backup_framework():
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = os.path.join(backup_dir, f"virgo_framework_backup_{timestamp}.zip")
    
    extensions_to_save = ('.py', '.json', '.txt')
    
    print(f"📦 Compressing agent-framework environment into {zip_filename}...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            if 'backups' in root or '.git' in root or '__pycache__' in root:
                continue
            for file in files:
                if file.endswith(extensions_to_save):
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, '.'))
                    print(f"  └── Added: {file}")
                    
    print(f"\n✅ Backup complete! Archive securely saved to {zip_filename}")

if __name__ == "__main__":
    backup_framework()
    input("\n[PRESS ENTER TO RETURN]")