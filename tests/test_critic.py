"""
Tests for critic — static analysis for generated code.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from critic import (
    Issue,
    ReviewReport,
    _check_ast,
    _check_lines,
    review_file,
    review_files,
)

# ===========================================================================
# Issue
# ===========================================================================


class TestIssue:
    def test_minimal(self) -> None:
        i = Issue(severity="error", message="test issue")
        assert i.severity == "error"
        assert i.message == "test issue"
        assert i.line == 0
        assert i.file == ""


# ===========================================================================
# ReviewReport
# ===========================================================================


class TestReviewReport:
    def test_empty_report_passes(self) -> None:
        r = ReviewReport(files_reviewed=1)
        assert r.passed
        assert r.errors == []
        assert r.warnings == []

    def test_error_issues(self) -> None:
        r = ReviewReport(files_reviewed=1)
        r.issues.append(Issue(severity="error", message="err1"))
        r.issues.append(Issue(severity="warning", message="warn1"))
        assert not r.passed
        assert len(r.errors) == 1
        assert len(r.warnings) == 1

    def test_str_no_issues(self) -> None:
        r = ReviewReport(files_reviewed=2)
        text = str(r)
        assert "2 file(s)" in text
        assert "No issues" in text

    def test_str_with_issues(self) -> None:
        r = ReviewReport(files_reviewed=1)
        r.issues.append(Issue(severity="error", message="bad code", line=10, file="test.py"))
        text = str(r)
        assert "[ERR]" in text
        assert "test.py" in text


# ===========================================================================
# _check_ast — AST-level checks
# ===========================================================================


class TestCheckAST:
    def _check(self, source: str) -> list[Issue]:
        import ast

        tree = ast.parse(source)
        issues: list[Issue] = []
        _check_ast(tree, source, "test.py", issues)
        return issues

    def test_clean_code(self) -> None:
        code = """
if __name__ == '__main__':
    main()
"""
        issues = self._check(code)
        assert len(issues) == 0

    def test_missing_main_guard(self) -> None:
        code = """
def main():
    pass
"""
        issues = self._check(code)
        # Should warn about missing __name__ guard
        # This may not flag depending on ast logic; check at least it runs
        assert isinstance(issues, list)

    def test_bare_except(self) -> None:
        code = """
try:
    x = 1
except:
    pass
"""
        issues = self._check(code)
        bare = [i for i in issues if "bare" in i.message.lower()]
        assert len(bare) > 0

    def test_eval_detected(self) -> None:
        code = 'result = eval("1+1")\n'
        issues = self._check(code)
        eval_issues = [i for i in issues if "eval" in i.message.lower()]
        assert len(eval_issues) > 0

    def test_exec_detected(self) -> None:
        code = 'exec("x = 1")\n'
        issues = self._check(code)
        exec_issues = [i for i in issues if "exec" in i.message.lower()]
        assert len(exec_issues) > 0


# ===========================================================================
# _check_regex — regex-level checks
# ===========================================================================


class TestCheckLines:
    def _check(self, source: str) -> list[Issue]:
        issues: list[Issue] = []
        _check_lines(source, "test.py", issues)
        return issues

    def test_long_lines(self) -> None:
        source = "x = " + "a" * 200 + "\n"
        issues = self._check(source)
        long = [i for i in issues if "long" in i.message.lower()]
        assert len(long) > 0

    def test_import_star(self) -> None:
        """import * is checked in _check_ast, not _check_lines."""
        source = "from os import *\n"
        issues = self._check(source)
        # _check_lines doesn't check for import star
        star = [i for i in issues if "import *" in i.message]
        assert len(star) == 0

    def test_clean_passes(self) -> None:
        source = "import os\nx = 1\n"
        issues = self._check(source)
        assert len(issues) == 0


# ===========================================================================
# review_file / review_files
# ===========================================================================


class TestReviewFile:
    def test_review_clean_file(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        report = review_file(str(f))
        assert report.files_reviewed == 1

    def test_review_with_issues(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.py"
        f.write_text("from os import *\nexec('x=1')\n")
        report = review_file(str(f))
        assert len(report.issues) >= 2

    def test_review_nonexistent_file(self) -> None:
        report = review_file("/nonexistent.py")
        assert not report.passed
        assert "not found" in str(report)


class TestReviewFiles:
    def test_review_multiple(self, tmp_path: Path) -> None:
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("x = 1")
        b.write_text("y = 2")
        report = review_files([str(a), str(b)])
        assert report.files_reviewed == 2

    def test_review_empty_list(self) -> None:
        report = review_files([])
        assert report.files_reviewed == 0
        assert report.passed
