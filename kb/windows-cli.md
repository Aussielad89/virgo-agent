# Windows CLI Quick Reference

Shell notes for this Windows10 box (MSYS/git-bash available). Use POSIX
syntax in scripts; PowerShell builtins won't run under bash.

## Essentials
- List files: `ls` (not `dir`). Find by name: `find . -name '*.py'`.
- Search content: `grep -rn "pattern" .` (ripgrep-backed search_files
  tool preferred over raw grep).
- Edit files: use the patch tool, not `sed`/`awk`.
- Read files: read_file tool, not `cat`/`head`/`tail`.

## Python
- System interpreter: `C:\Python314\python.exe` (has PyQt6 6.11 + pytest).
- Run a script: `/c/Python314/python.exe script.py`.
- Make dirs: `mkdir -p path` (bash) — parent auto-created.

## Git
- Push auth: Git Credential Manager cached cred — `git push` works with NO
  token in URL. Do NOT paste tokens into chat.
- Cached GCM token is often `gho_` OAuth: works for git, NOT API writes
  (empty X-OAuth-Scopes). For API writes, make a PAT with `repo` scope.

## Networking (red team — authorized only)
- Subnet sweep: nmap / `net_scan.py` (ping sweep, 500ms timeout).
- Port scan: nmap `-sT` (userspace, no SYN). See redteam-toolkit.md.

## Housekeeping
- Route generated output to gitignored `output/` — never litter repo root.
