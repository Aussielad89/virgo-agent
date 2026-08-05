$proj = "C:\Users\paren\OneDrive\Desktop\agent-framework"
$icon = Join-Path $proj "logo.ico"
$bat = Join-Path $proj "launch_virgo_desktop.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Virgo Desktop.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = $bat
$shortcut.WorkingDirectory = $proj
$shortcut.Description = "Virgo Desktop multi-agent framework GUI"
$shortcut.IconLocation = $icon
$shortcut.WindowStyle = 1
$shortcut.Save()
