from setuptools import setup

setup(
    py_modules=[
        "_console", "_log",
        "agent_runtime", "autodepend",
        "blackboard",
        "cli", "config", "critic",
        "environment", "evaluator", "experience", "exporter",
        "logo",
        "main", "mcp_bridge", "memory",
        "orchestrator",
        "plugins",
        "run",
        "server",
        "templates", "tools", "tools_core",
        "virgo_alerts", "virgo_analyzer", "virgo_backup",
        "virgo_diagnostics", "virgo_docgen",
        "virgo_finder", "virgo_fingerprinter", "virgo_fixer",
        "virgo_menu",
        "virgo_network_scanner", "virgo_run",
        "virgo_sandbox", "virgo_scaffold",
        "virgo_watchdog", "virgo_web_search", "virgo_webhook",
        "workflow", "workflow_check",
    ],
)
