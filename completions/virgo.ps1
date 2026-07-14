# PowerShell completion for virgo
# Usage:  virgo completion powershell | Out-String | Invoke-Expression
# Install: virgo completion powershell > $PROFILE

Register-ArgumentCompleter -Native -CommandName virgo -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @('run', 'serve', 'list', 'replay', 'feedback', 'demo',
                  'templates', 'export', 'plugins', 'scaffold', 'completion')
    $scaffoldSub = @('list', 'show', 'generate', 'gen', 'g')

    $words = $commandAst.CommandElements | ForEach-Object { $_.Value }
    $currentIndex = $words.Count - 1
    $current = $words[$currentIndex] -replace '^-+'

    function Get-Scaffolds {
        python -c "from virgo_scaffold import list_scaffolds; [print(s['name']) for s in list_scaffolds()]" 2>$null
    }

    function Get-ScaffoldVars($name) {
        python -c @"
from virgo_scaffold import load_scaffold
import sys
s = load_scaffold(sys.argv[1])
if s:
    for k in s.get('prompts', {}):
        print(k + '=')
"@ $name 2>$null
    }

    if ($currentIndex -eq 1) {
        return $commands | Where-Object { $_ -like "$wordToComplete*" }
    }

    switch ($words[1]) {
        'run' {
            $opts = @('--goal', '-g', '--iterations', '-i', '--name', '-n',
                      '--llm', '--critic', '--auto-depend', '--config', '-c')
            return $opts | Where-Object { $_ -like "$wordToComplete*" }
        }
        'serve' {
            $opts = @('--host', '--port', '-p')
            return $opts | Where-Object { $_ -like "$wordToComplete*" }
        }
        'scaffold' {
            if ($currentIndex -eq 2) {
                return $scaffoldSub | Where-Object { $_ -like "$wordToComplete*" }
            }
            if ($words[2] -in @('generate', 'gen', 'g')) {
                if ($currentIndex -eq 3) {
                    return (Get-Scaffolds) | Where-Object { $_ -like "$wordToComplete*" }
                }
                $opts = @('--output', '-o', '--var', '-v')
                return $opts | Where-Object { $_ -like "$wordToComplete*" }
            }
            if ($words[2] -eq 'show' -and $currentIndex -eq 3) {
                return (Get-Scaffolds) | Where-Object { $_ -like "$wordToComplete*" }
            }
        }
        'templates' {
            $opts = @('--generate', '-g', '--output', '-o', '--name', '-n',
                      '--description', '-d', '--target', '-t')
            return $opts | Where-Object { $_ -like "$wordToComplete*" }
        }
        'completion' {
            return @('bash', 'zsh', 'powershell') | Where-Object { $_ -like "$wordToComplete*" }
        }
    }
}
