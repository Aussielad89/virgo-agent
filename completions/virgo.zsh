# zsh completion for virgo
# Source:  source <(virgo completion zsh)
# Install: cp completions/virgo.zsh /usr/share/zsh/site-functions/_virgo

#compdef virgo virgo-dashboard

_virgo_commands() {
    local -a commands
    commands=(
        'run:Run the pipeline'
        'serve:Start the web dashboard'
        'list:List saved sessions'
        'replay:Replay a saved session'
        'feedback:Show feedback memory'
        'demo:Run the demo pipeline'
        'templates:Generate code from templates'
        'export:Export a session'
        'plugins:List and load plugins'
        'scaffold:Generate project from a scaffold'
        'completion:Generate shell completion script'
    )
    _describe 'command' commands
}

_virgo_scaffold_names() {
    local -a scaffolds
    scaffolds=(${(f)"$(python -c "from virgo_scaffold import list_scaffolds; [print(s['name']) for s in list_scaffolds()]" 2>/dev/null)"})
    _describe 'scaffold' scaffolds
}

_virgo_scaffold_vars() {
    local scaffold=$1
    local -a vars
    vars=(${(f)"$(python -c "
from virgo_scaffold import load_scaffold
import sys
s = load_scaffold(sys.argv[1])
if s:
    for k in s.get('prompts', {}):
        print(k + '=')
" $scaffold 2>/dev/null)"})
    _describe 'var' vars
}

_virgo_run_opts() {
    local -a opts
    opts=(
        '--goal:-g:Goal string'
        '--iterations:-i:Max WTF iterations'
        '--name:-n:Session name'
        '--llm:Use LLM-backed policies'
        '--critic:Run static analysis'
        '--auto-depend:Auto-install dependencies'
        '--config:-c:Pipeline config file'
    )
    _describe 'option' opts
}

_virgo() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    _arguments -C \
        '1: :_virgo_commands' \
        '*::arg:->args'

    case $state in
        args)
            case $words[1] in
                run)
                    _arguments \
                        '--goal=-[Goal string]:goal' \
                        '--iterations=-[Max WTF iterations]::(1 3 5 10)' \
                        '--name=-[Session name]:name' \
                        '--llm[Use LLM-backed policies]' \
                        '--critic[Run static analysis]' \
                        '--auto-depend[Auto-install dependencies]' \
                        '--config=-[Pipeline config file]:file:_files'
                    ;;
                serve)
                    _arguments \
                        '--host=-[Host to bind]:host' \
                        '--port=-[Port]:port'
                    ;;
                scaffold)
                    if ((CURRENT == 2)); then
                        local -a subcmds
                        subcmds=('list:List available scaffolds' 'show:Show scaffold details' 'generate:Generate project' 'gen:Alias for generate')
                        _describe 'subcommand' subcmds
                    else
                        case $words[2] in
                            generate|gen|g)
                                if ((CURRENT == 3)); then
                                    _virgo_scaffold_names
                                else
                                    _arguments \
                                        '--output=-[Output directory]:directory:_files -/' \
                                        '--var=-[Template variable]:var:_virgo_scaffold_vars $words[3]'
                                fi
                                ;;
                            show)
                                _virgo_scaffold_names
                                ;;
                        esac
                    fi
                    ;;
                templates)
                    _arguments \
                        '--generate=-[Template key]:template' \
                        '--output=-[Output file]:file:_files' \
                        '--name=-[Project name]:name' \
                        '--description=-[Description]:description' \
                        '--target=-[Target module]:target'
                    ;;
                replay|export)
                    _arguments '*:file:_files'
                    ;;
                completion)
                    _arguments '1:shell:(bash zsh powershell)'
                    ;;
            esac
            ;;
    esac
}

compdef _virgo virgo virgo-dashboard
