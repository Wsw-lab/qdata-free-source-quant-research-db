from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TOOLCHAIN = ROOT / ".github" / "ci-toolchain.txt"
PYPROJECT = ROOT / "pyproject.toml"
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README_EN.md"
ADR = ROOT / "docs" / "adr" / "0001-research-snapshot-and-time-contract.md"
NOTEBOOK = ROOT / "notebooks" / "free_source_factor_backtest.ipynb"

EXPECTED_TOOLCHAIN = {
    "pip": "25.1.1",
    "setuptools": "75.8.2",
    "wheel": "0.45.1",
}


def _exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)==([A-Za-z0-9_.+-]+)", stripped)
        if not match:
            raise AssertionError(f"toolchain entry is not an exact pin: {stripped}")
        pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


class PublicSurfaceContractTest(unittest.TestCase):
    def test_ci_bootstraps_exact_toolchain_before_offline_editable_install(self) -> None:
        self.assertTrue(TOOLCHAIN.is_file(), "missing pinned CI toolchain file")
        self.assertEqual(_exact_pins(TOOLCHAIN), EXPECTED_TOOLCHAIN)

        workflow = WORKFLOW.read_text(encoding="utf-8")
        bootstrap = workflow.index("- name: Install pinned packaging toolchain")
        verify = workflow.index("- name: Verify packaging toolchain versions")
        project_install = workflow.index("- name: Install package")
        outside_import = workflow.index("- name: Verify installed package import")
        self.assertLess(bootstrap, verify)
        self.assertLess(verify, project_install)
        self.assertLess(project_install, outside_import)
        self.assertIn(
            "python -m pip install --disable-pip-version-check -r .github/ci-toolchain.txt",
            workflow,
        )
        self.assertIn(
            "python -m pip install --no-index --no-deps --no-build-isolation -e .",
            workflow,
        )
        self.assertIn("working-directory: ${{ runner.temp }}", workflow)
        self.assertIn('python -c "import qdata; print(qdata.__file__)"', workflow)
        for package, version in EXPECTED_TOOLCHAIN.items():
            self.assertIn(f'"{package}": "{version}"', workflow)

        pyproject = PYPROJECT.read_text(encoding="utf-8")
        minimum = re.search(r'"setuptools>=(\d+)"', pyproject)
        self.assertIsNotNone(minimum)
        pinned_major = int(EXPECTED_TOOLCHAIN["setuptools"].split(".", 1)[0])
        self.assertGreaterEqual(pinned_major, int(minimum.group(1)))

    def test_python_support_claim_matches_project_and_ci_matrix(self) -> None:
        pyproject = PYPROJECT.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.9,<3.13"', pyproject)
        self.assertIn(
            'python-version: ["3.9", "3.10", "3.11", "3.12"]', workflow
        )
        for readme in (README_ZH, README_EN):
            text = readme.read_text(encoding="utf-8")
            self.assertIn("Python 3.9–3.12", text)
            self.assertNotIn("Python 3.9+", text)

    def test_public_arithmetic_example_has_unambiguous_name(self) -> None:
        new_example = ROOT / "examples" / "factor_api_arithmetic_demo.py"
        new_test = ROOT / "tests" / "test_factor_api_arithmetic_demo.py"
        old_example = ROOT / "examples" / ("factor_" + "backtest_demo.py")
        old_test = ROOT / "tests" / ("test_factor_" + "backtest_demo.py")
        self.assertTrue(new_example.is_file())
        self.assertTrue(new_test.is_file())
        self.assertFalse(old_example.exists())
        self.assertFalse(old_test.exists())

        old_stem = "factor_" + "backtest_demo"
        surfaces = [README_ZH, README_EN, WORKFLOW, ADR]
        surfaces.extend((ROOT / "docs").rglob("*.md"))
        surfaces.extend((ROOT / "examples").glob("*.py"))
        surfaces.extend((ROOT / "notebooks").glob("*.ipynb"))
        surfaces.extend((ROOT / "tests").glob("*.py"))
        for path in surfaces:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn(old_stem, path.read_text(encoding="utf-8"))

    def test_database_evidence_distinguishes_verified_selector_from_open_work(self) -> None:
        required_evidence = (
            "ClickHouse 24.8.14.39",
            "fresh old-key full schemas",
            "four source rows in one old-key part",
            "create-copy-EXCHANGE",
            "old-key backup",
            "OPTIMIZE FINAL",
        )
        open_work = (
            "PostgreSQL array binding",
            "query plans",
            "cross-store transactions",
            "CI does not run database integration",
        )
        for document in (README_ZH, README_EN, ADR):
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(ROOT)):
                for marker in required_evidence + open_work:
                    self.assertIn(marker, text)

    def test_public_notebook_labels_mock_results_as_timing_arithmetic(self) -> None:
        text = NOTEBOOK.read_text(encoding="utf-8")
        self.assertNotIn("QData factor backtest demo", text)
        self.assertNotIn("strategy return", text.lower())
        self.assertIn("factor_api_arithmetic_demo", text)
        self.assertIn("after_close", text)
        self.assertIn("next_session_open", text)
        self.assertIn("not strategy performance", text.lower())

    def test_public_docs_do_not_publish_stale_test_counts(self) -> None:
        paths = list((ROOT / "docs").rglob("*"))
        paths.extend(ROOT.glob("*.md"))
        for path in paths:
            if path.suffix.lower() not in {".html", ".md", ".svg"}:
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("291", text)
                if (ROOT / "docs") in path.parents:
                    self.assertIsNone(
                        re.search(r"\b\d+\s+tests?\b", text, flags=re.IGNORECASE)
                    )

    def test_public_site_does_not_present_stale_dynamic_metrics(self) -> None:
        paths = (
            ROOT / "docs" / "index.html",
            ROOT / "docs" / "assets" / "preview-board.html",
            ROOT / "docs" / "assets" / "qdata-architecture.svg",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("73 console smoke markers", text)
                self.assertNotIn("html_bytes=807462 markers=73", text)
                self.assertNotIn("health=ok rows=1", text)
                self.assertNotRegex(
                    text,
                    r"<strong>\d+</strong><small>(?:console smoke markers|free source candidates)</small>",
                )


if __name__ == "__main__":
    unittest.main()
