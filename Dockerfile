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
COPY orchestrator.py tools.py environment.py memory.py critic.py autodepend.py config.py plugins.py ./
COPY server.py exporter.py templates.py workflow.py workflow_check.py logo.py ./
COPY virgo_alerts.py virgo_analyzer.py virgo_backup.py ./
COPY virgo_diagnostics.py virgo_finder.py virgo_fingerprinter.py virgo_fixer.py ./
COPY virgo_menu.py virgo_network_scanner.py virgo_run.py virgo_sandbox.py ./
COPY virgo_scaffold.py virgo_watchdog.py virgo_web_search.py virgo_webhook.py ./

# Copy scaffolds
COPY scaffolds/ scaffolds/

# Install (editable mode for development)
RUN pip install -e .

# Expose web dashboard port
EXPOSE 8765

# Default: run the web dashboard
CMD ["virgo", "serve", "--host", "0.0.0.0", "--port", "8765"]
