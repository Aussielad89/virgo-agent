"""
autodepend — scan generated Python files for imports and
auto-install missing third-party packages in the agent environment.
"""

from __future__ import annotations

import ast
from typing import Any

# Standard library module names (Python 3.14, but stable enough)
_STDLIB_MODULES: set[str] = {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
    "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
    "binhex", "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb",
    "chunk", "cmath", "cmd", "code", "codecs", "codeop", "collections",
    "colorsys", "compileall", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "cProfile", "crypt", "csv", "ctypes",
    "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
    "dis", "distutils", "doctest", "email", "encodings", "enum",
    "errno", "faulthandler", "fcntl", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "graphlib", "grp", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
    "imghdr", "imp", "importlib", "inspect", "io", "ipaddress",
    "itertools", "json", "keyword", "lib2to3", "linecache", "locale",
    "logging", "lzma", "mailbox", "mailcap", "marshal", "math", "mimetypes",
    "mmap", "modulefinder", "multiprocessing", "netrc", "nis", "nntplib",
    "numbers", "operator", "optparse", "os", "ossaudiodev", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource",
    "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib",
    "sndhdr", "socket", "socketserver", "sqlite3", "ssl", "stat",
    "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib",
    "uu", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    # Common names that are actually third-party but often bundled
    "setuptools", "pip", "ensurepip",
}

# Modules whose top-level package is third-party
_KNOWN_THIRD_PARTY: dict[str, str] = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "Image": "pillow",
    "cv2": "opencv-python",
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "jinja2": "jinja2",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "click": "click",
    "rich": "rich",
    "tqdm": "tqdm",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "sklearn": "scikit-learn",
    "torch": "torch",
    "tensorflow": "tensorflow",
    "django": "django",
    "bs4": "beautifulsoup4",
    "selenium": "selenium",
    "playwright": "playwright",
}


def extract_imports(code: str) -> list[str]:
    """Extract all imported module names from a Python source string.

    Returns the top-level package name for each import (e.g. 'os.path' → 'os').
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                imports.add(top)
    return sorted(imports)


def classify_import(module: str) -> str:
    """Return 'stdlib', 'third_party', or 'unknown' for a module name."""
    if module in _STDLIB_MODULES:
        return "stdlib"
    if module in _KNOWN_THIRD_PARTY:
        return "third_party"
    # Builtins that ast can't catch
    if module in ("__future__", "__init__"):
        return "stdlib"
    return "unknown"


def auto_install(
    code: str,
    env: Any,  # AgentEnvironment
    quiet: bool = True,
) -> list[str]:
    """Scan *code* for imports and install missing third-party packages.

    Returns list of installed package names.
    """
    installed: list[str] = []
    for mod in extract_imports(code):
        category = classify_import(mod)
        if category == "third_party":
            pkg = _KNOWN_THIRD_PARTY[mod]
            try:
                env.ensure(pkg, quiet=quiet)
                installed.append(pkg)
            except Exception:
                pass  # best effort
    return installed
