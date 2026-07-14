# bash completion for virgo
# Source:  source <(virgo completion bash)
# Install: virgo completion bash > /etc/bash_completion.d/virgo

_virgo_completions() {
    local cur prev words cword
    _init_completion || return

    # All subcommands
    local commands="run serve list replay feedback demo templates export plugins scaffold completion"

    # Scaffold subcommands
    local scaffold_cmds="list show generate gen g"

    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return
    fi

    case "${words[1]}" in
        run)
            case "$prev" in
                -g|--goal|-n|--name|-c|--config)
                    # No completion for string args
                    return
                    ;;
                -i|--iterations)
                    COMPREPLY=($(compgen -W "1 3 5 10" -- "$cur"))
                    return
                    ;;
                *)
                    COMPREPLY=($(compgen -W "--goal -g --iterations -i --name -n --llm --critic --auto-depend --config -c --help -h" -- "$cur"))
                    return
                    ;;
            esac
            ;;
        serve)
            case "$prev" in
                --host)
                    COMPREPLY=($(compgen -W "127.0.0.1 0.0.0.0 localhost" -- "$cur"))
                    return
                    ;;
                -p|--port)
                    COMPREPLY=($(compgen -W "8765 8000 8080 3000" -- "$cur"))
                    return
                    ;;
                *)
                    COMPREPLY=($(compgen -W "--host --port -p --help -h" -- "$cur"))
                    return
                    ;;
            esac
            ;;
        scaffold)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "$scaffold_cmds" -- "$cur"))
                return
            fi
            case "${words[2]}" in
                generate|gen|g)
                    case "$prev" in
                        -o|--output)
                            # Directory completion
                            _filedir -d
                            return
                            ;;
                        -v|--var)
                            # Suggest variable names from scaffold
                            if [[ -n "${words[3]}" ]]; then
                                local scaffold_name="${words[3]}"
                                local vars=$(_virgo_scaffold_vars "$scaffold_name")
                                COMPREPLY=($(compgen -W "$vars" -- "$cur"))
                            fi
                            return
                            ;;
                        *)
                            if [[ $cword -eq 3 ]]; then
                                # Suggest scaffold names
                                local scaffolds=$(_virgo_scaffold_list)
                                COMPREPLY=($(compgen -W "$scaffolds" -- "$cur"))
                            else
                                COMPREPLY=($(compgen -W "--output -o --var -v --help -h" -- "$cur"))
                            fi
                            return
                            ;;
                    esac
                    ;;
                show)
                    if [[ $cword -eq 3 ]]; then
                        local scaffolds=$(_virgo_scaffold_list)
                        COMPREPLY=($(compgen -W "$scaffolds" -- "$cur"))
                    fi
                    return
                    ;;
            esac
            ;;
        replay|export)
            if [[ $cword -eq 2 ]]; then
                _filedir
                return
            fi
            ;;
        templates)
            COMPREPLY=($(compgen -W "--generate -g --output -o --name -n --description -d --target -t --help -h" -- "$cur"))
            ;;
        completion)
            COMPREPLY=($(compgen -W "bash zsh powershell" -- "$cur"))
            ;;
    esac
}

# Helper: list scaffold names
_virgo_scaffold_list() {
    python -c "from virgo_scaffold import list_scaffolds; print(' '.join(s['name'] for s in list_scaffolds()))" 2>/dev/null
}

# Helper: list template variables for a scaffold
_virgo_scaffold_vars() {
    python -c "
from virgo_scaffold import load_scaffold
import sys
s = load_scaffold(sys.argv[1])
if s:
    prompts = s.get('prompts', {})
    print(' '.join(f'{k}=' for k in prompts))
" "$1" 2>/dev/null
}

complete -F _virgo_completions virgo
complete -F _virgo_completions virgo-dashboard
