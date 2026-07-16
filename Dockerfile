# Virgo — Multi-Agent State Machine
#
# Build:  docker build -t virgo .
# Run:    docker run -p 8765:8765 virgo
#
# Volumes for persistence:
#   docker run -p 8765:8765 -v virgo_data:/app/.virgo_memory virgo

FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir build

# Copy package definition
COPY pyproject.toml setup.py MANIFEST.in README.md LICENSE ./

# Copy all source modules
COPY __init__.py _console.py _log.py ./
COPY cli.py run.py main.py ./
COPY agent_runtime.py blackboard.py config.py critic.py ./
COPY environment.py evaluator.py experience.py exporter.py generators.py ./
COPY mcp_bridge.py memory.py orchestrator.py plugins.py ./
COPY server.py subagent.py templates.py tools.py tools_core.py ./
COPY workflow.py workflow_check.py logo.py ./
COPY virgo_alerts.py virgo_analyzer.py virgo_backup.py ./
COPY virgo_diagnostics.py virgo_diff.py virgo_docgen.py ./
COPY virgo_finder.py virgo_fingerprinter.py virgo_fixer.py ./
COPY virgo_git.py virgo_init.py virgo_menu.py ./
COPY virgo_network_scanner.py virgo_run.py virgo_sandbox.py ./
COPY virgo_scaffold.py virgo_testgen.py virgo_watchdog.py virgo_watcher.py ./
COPY virgo_web_search.py virgo_webhook.py ./

# Copy scaffolds & completions
COPY scaffolds/ scaffolds/
COPY completions/ completions/

# Install (with web dashboard & YAML support)
RUN pip install .[web,yaml]

# Create venv symlink for CLI helpers
ENV PATH="/app/.venv/bin:$PATH"

# Expose web dashboard port
EXPOSE 8765

# Default: run the web dashboard
CMD ["virgo", "serve", "--host", "0.0.0.0", "--port", "8765"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')" || exit 1
