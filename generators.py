"""
generators — multi-language code generators for virgo.

Provides template-based scaffolding for JavaScript, TypeScript, Rust,
and Go projects. Each generator implements the ``BaseGenerator`` protocol
with a ``generate(plan)`` method that returns ``[(file_path, content), …]``
tuples — the same format expected by the orchestrator's ``code_gen``
callback.

Usage::

    from generators import get_generator

    gen = get_generator("js")
    files = gen.generate("a CLI tool that parses logs")
    for path, content in files:
        print(f"{path}  ({len(content)} B)")
"""

from __future__ import annotations

import textwrap
from typing import Protocol

# ── Protocol ───────────────────────────────────────────────────────────────


class BaseGenerator(Protocol):
    """Protocol all language generators must satisfy.

    Implement ``generate(plan: str) -> list[tuple[str, str]]`` where
    each tuple is ``(relative_file_path, file_contents)``.
    """

    def generate(self, plan: str) -> list[tuple[str, str]]: ...


# ── Shared helpers ─────────────────────────────────────────────────────────


def _snake_to_pascal(name: str) -> str:
    """Convert a snake_case or kebab-case string to PascalCase."""
    import re

    return "".join(word.capitalize() for word in re.split(r"[-_ ]+", name) if word)


def _project_name_from_plan(plan: str) -> str:
    """Derive a short project name from the plan string."""
    # Take the first meaningful noun phrase (max 3 words, alphanumeric)
    words = plan.strip().split()
    if not words:
        return "app"
    clean = [w.strip(".,;:!?\"'()[]") for w in words[:4] if w.strip(".,;:!?\"'()[]")]
    name = "_".join(clean).lower()
    if not name:
        return "app"
    return name.replace("-", "_")


def _comment_char(lang: str) -> str:
    """Return the single-line comment marker for a language."""
    return {"js": "//", "ts": "//", "rs": "//", "go": "//"}.get(lang, "#")


# ── JavaScript Generator ───────────────────────────────────────────────────


class JavaScriptGenerator:
    """Generate JavaScript project scaffolding (Node.js / CommonJS)."""

    def generate(self, plan: str) -> list[tuple[str, str]]:
        name = _project_name_from_plan(plan)
        main_file = "index.js"

        package_json = {
            "name": name,
            "version": "1.0.0",
            "description": plan.strip().splitlines()[0] if plan else "Generated JS project",
            "main": main_file,
            "scripts": {
                "start": f"node {main_file}",
                "test": "node --test",
            },
            "license": "MIT",
        }

        # Package.json
        import json

        files: list[tuple[str, str]] = [
            ("package.json", json.dumps(package_json, indent=2) + "\n"),
        ]

        # Main entry point
        main_content = textwrap.dedent(f"""\
            /*
             * {name}
             *
             * {plan.strip()}
             */

            "use strict";

            /** Main entry point. */
            function main() {{
                console.log("Hello from {name}!");
            }}

            if (require.main === module) {{
                main();
            }}

            module.exports = {{ main }};
        """)

        files.append((main_file, main_content))

        # Basic README
        readme = textwrap.dedent(f"""\
            # {name}

            {plan.strip()}

            ## Usage

            ```bash
            npm start
            npm test
            ```
        """)
        files.append(("README.md", readme))

        return files


# ── TypeScript Generator ──────────────────────────────────────────────────


class TypeScriptGenerator:
    """Generate TypeScript project scaffolding with tsconfig."""

    def generate(self, plan: str) -> list[tuple[str, str]]:
        name = _project_name_from_plan(plan)
        main_file = "src/index.ts"

        tsconfig = {
            "compilerOptions": {
                "target": "ES2022",
                "module": "Node16",
                "moduleResolution": "Node16",
                "outDir": "./dist",
                "rootDir": "./src",
                "strict": True,
                "esModuleInterop": True,
                "skipLibCheck": True,
                "forceConsistentCasingInFileNames": True,
                "declaration": True,
                "declarationMap": True,
                "sourceMap": True,
            },
            "include": ["src/**/*"],
            "exclude": ["node_modules", "dist"],
        }

        import json

        pkg = {
            "name": name,
            "version": "1.0.0",
            "description": plan.strip().splitlines()[0] if plan else "Generated TS project",
            "main": f"dist/{main_file.replace('.ts', '.js').replace('src/', '')}",
            "types": f"dist/{main_file.replace('.ts', '.d.ts').replace('src/', '')}",
            "scripts": {
                "build": "tsc",
                "start": "node dist/index.js",
                "test": "jest",
            },
            "license": "MIT",
        }

        files: list[tuple[str, str]] = [
            ("tsconfig.json", json.dumps(tsconfig, indent=2) + "\n"),
            ("package.json", json.dumps(pkg, indent=2) + "\n"),
        ]

        # Main .ts entry
        main_content = textwrap.dedent(f"""\
            /**
             * {name}
             *
             * {plan.strip()}
             */

            /** Application entry point. */
            export function main(): void {{
                console.log("Hello from {name}!");
            }}

            if (require.main === module) {{
                main();
            }}
        """)
        files.append((main_file, main_content))

        # README
        readme = textwrap.dedent(f"""\
            # {name}

            {plan.strip()}

            ## Setup

            ```bash
            npm install
            ```

            ## Build & Run

            ```bash
            npm run build
            npm start
            ```
        """)
        files.append(("README.md", readme))

        return files


# ── Rust Generator ─────────────────────────────────────────────────────────


class RustGenerator:
    """Generate Rust project scaffolding (Cargo.toml + src/main.rs or lib.rs)."""

    def generate(self, plan: str) -> list[tuple[str, str]]:
        name = _project_name_from_plan(plan).replace("_", "-")
        # Determine whether the plan suggests a library or binary
        is_lib = any(kw in plan.lower() for kw in ("library", "lib", "module", "reusable"))

        files: list[tuple[str, str]] = []

        # Cargo.toml
        cargo = textwrap.dedent(f"""\
            [package]
            name = "{name}"
            version = "0.1.0"
            edition = "2021"
            description = "{plan.strip().splitlines()[0] if plan else f"{name} project"}"

            [dependencies]

            [features]
        """)
        files.append(("Cargo.toml", cargo))

        if is_lib:
            # Library crate
            lib_content = textwrap.dedent(f"""\
                /// `{name}` — {plan.strip().splitlines()[0] if plan else "a Rust library"}
                ///
                /// {plan.strip()}

                /// Greet the world.
                pub fn hello() -> String {{
                    format!("Hello from {name}!")
                }}

                #[cfg(test)]
                mod tests {{
                    use super::*;

                    #[test]
                    fn test_hello() {{
                        assert_eq!(hello(), format!("Hello from {name}!"));
                    }}
                }}
            """)
            files.append(("src/lib.rs", lib_content))
        else:
            # Binary crate
            main_content = textwrap.dedent(f"""\
                /// `{name}` — {plan.strip().splitlines()[0] if plan else "a Rust binary"}
                ///
                /// {plan.strip()}

                fn main() {{
                    println!("Hello from {name}!");
                }}
            """)
            files.append(("src/main.rs", main_content))

        # README
        readme = textwrap.dedent(f"""\
            # {name}

            {plan.strip()}

            ## Build & Run

            ```bash
            cargo build
            cargo run
            cargo test
            ```
        """)
        files.append(("README.md", readme))

        return files


# ── Go Generator ──────────────────────────────────────────────────────────


class GoGenerator:
    """Generate Go project scaffolding (go.mod + main.go)."""

    def generate(self, plan: str) -> list[tuple[str, str]]:
        name = _project_name_from_plan(plan).replace("_", "-")
        module_path = f"github.com/user/{name}"

        files: list[tuple[str, str]] = []

        # go.mod
        go_mod = textwrap.dedent(f"""\
            module {module_path}

            go 1.21
        """)
        files.append(("go.mod", go_mod))

        # main.go
        main_content = textwrap.dedent(f"""\
            // {name}
            //
            // {plan.strip()}

            package main

            import "fmt"

            func main() {{
                fmt.Println("Hello from {name}!")
            }}
        """)
        files.append(("main.go", main_content))

        # README
        readme = textwrap.dedent(f"""\
            # {name}

            {plan.strip()}

            ## Usage

            ```bash
            go run .
            go build -o {name}
            ```
        """)
        files.append(("README.md", readme))

        return files


# ── Dispatch ────────────────────────────────────────────────────────────────

LANG_GENERATORS: dict[str, type[BaseGenerator]] = {
    "js": JavaScriptGenerator,
    "ts": TypeScriptGenerator,
    "rs": RustGenerator,
    "go": GoGenerator,
}

# Language aliases — map common alternatives to canonical keys
_LANG_ALIASES: dict[str, str] = {
    "javascript": "js",
    "node": "js",
    "nodejs": "js",
    "typescript": "ts",
    "rust": "rs",
    "golang": "go",
}


def get_generator(lang: str) -> BaseGenerator:
    """Resolve a language name to a generator instance.

    Parameters
    ----------
    lang : str
        One of ``js``, ``ts``, ``rs``, ``go``, or a common alias
        (``javascript``, ``typescript``, ``rust``, ``golang``, …).

    Returns
    -------
    BaseGenerator
        An instance of the matching generator class.

    Raises
    ------
    KeyError
        If *lang* is not recognised.
    """
    canonical = _LANG_ALIASES.get(lang.lower(), lang.lower())
    cls = LANG_GENERATORS.get(canonical)
    if cls is None:
        available = ", ".join(sorted(LANG_GENERATORS))
        raise KeyError(f"Unknown language {lang!r}. Available: {available}")
    return cls()


def generate(lang: str, plan: str) -> list[tuple[str, str]]:
    """Shorthand: resolve *lang* and call ``generate(plan)`` in one step.

    Returns
    -------
    list[tuple[str, str]]
        ``[(file_path, content), …]``
    """
    return get_generator(lang).generate(plan)
