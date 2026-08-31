from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TOOLCHAIN = ROOT / ".github" / "ci-toolchain.txt"
PYPROJECT = ROOT / "pyproject.toml"
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README_EN.md"
SNAPSHOT_ADR = ROOT / "docs" / "adr" / "0001-research-snapshot-and-time-contract.md"
TIMING_ADR = ROOT / "docs" / "adr" / "0002-after-close-signal-timing.md"
EXAMPLE = ROOT / "examples" / "factor_api_arithmetic_demo.py"
NOTEBOOK = ROOT / "notebooks" / "free_source_factor_api_arithmetic.ipynb"
OLD_NOTEBOOK = ROOT / "notebooks" / ("free_source_factor_" + "backtest.ipynb")
INTEGRATION_REPORT = ROOT / "integration-report.md"

EXPECTED_TOOLCHAIN = {
    "pip": "26.2.1",
    "setuptools": "84.0.0",
    "wheel": "0.48.0",
    "packaging": "26.3",
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


def _public_documents() -> list[Path]:
    paths = [README_ZH, README_EN, INTEGRATION_REPORT]
    paths.extend((ROOT / "docs").rglob("*"))
    return sorted(
        {path for path in paths if path.suffix.lower() in {".html", ".md", ".svg"}}
    )


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
            "python -m pip install --disable-pip-version-check --no-deps -r .github/ci-toolchain.txt",
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
        self.assertEqual(int(minimum.group(1)), 83)
        pinned_major = int(EXPECTED_TOOLCHAIN["setuptools"].split(".", 1)[0])
        self.assertGreaterEqual(pinned_major, int(minimum.group(1)))

    def test_python_support_claim_matches_project_and_ci_matrix(self) -> None:
        pyproject = PYPROJECT.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.10,<3.13"', pyproject)
        self.assertIn('python-version: ["3.10", "3.11", "3.12"]', workflow)
        self.assertNotIn('"3.9"', workflow)
        for readme in (README_ZH, README_EN):
            text = readme.read_text(encoding="utf-8")
            self.assertIn("Python 3.10–3.12", text)
            self.assertNotIn("Python 3.9", text)

    def test_public_arithmetic_example_and_notebook_have_unambiguous_names(self) -> None:
        new_test = ROOT / "tests" / "test_factor_api_arithmetic_demo.py"
        old_example = ROOT / "examples" / ("factor_" + "backtest_demo.py")
        old_test = ROOT / "tests" / ("test_factor_" + "backtest_demo.py")
        self.assertTrue(EXAMPLE.is_file())
        self.assertTrue(new_test.is_file())
        self.assertTrue(NOTEBOOK.is_file())
        self.assertFalse(OLD_NOTEBOOK.exists())
        self.assertFalse(old_example.exists())
        self.assertFalse(old_test.exists())

        old_stems = ("factor_" + "backtest_demo", "free_source_factor_" + "backtest")
        surfaces = [README_ZH, README_EN, WORKFLOW, SNAPSHOT_ADR, TIMING_ADR]
        surfaces.extend((ROOT / "docs").rglob("*.md"))
        surfaces.extend((ROOT / "examples").glob("*.py"))
        surfaces.extend((ROOT / "notebooks").glob("*.ipynb"))
        surfaces.extend((ROOT / "tests").glob("*.py"))
        for path in surfaces:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                for old_stem in old_stems:
                    self.assertNotIn(old_stem, text)

    def test_arithmetic_surface_is_adjusted_reference_not_execution(self) -> None:
        notebook_path = NOTEBOOK if NOTEBOOK.exists() else OLD_NOTEBOOK
        surfaces = {
            EXAMPLE: EXAMPLE.read_text(encoding="utf-8"),
            README_ZH: README_ZH.read_text(encoding="utf-8"),
            README_EN: README_EN.read_text(encoding="utf-8"),
            TIMING_ADR: TIMING_ADR.read_text(encoding="utf-8"),
            notebook_path: notebook_path.read_text(encoding="utf-8"),
        }
        forbidden_identifiers = (
            "fill_timing",
            "entry_open",
            "exit_close",
            "next_return",
            "long_return",
            "short_return",
            "benchmark_return",
            "active_return",
            "factor_spread",
        )
        for path, text in surfaces.items():
            with self.subTest(path=path.relative_to(ROOT)):
                for identifier in forbidden_identifiers:
                    self.assertNotIn(identifier, text)
                self.assertNotIn("fill price", text.lower())
                self.assertNotIn("作为成交价", text)

        example = surfaces[EXAMPLE]
        self.assertIn('adjust="forward"', example)
        for field in (
            "adjusted_open_reference",
            "adjusted_close_mark",
            "marked_change",
            "reference_timing",
            "next_session_tradability_verified",
        ):
            self.assertIn(field, example)

        self.assertIn("前复权参考算术", surfaces[README_ZH])
        self.assertIn("未验证下一交易日可交易性", surfaces[README_ZH])
        self.assertIn("不是成交、执行或回测", surfaces[README_ZH])
        self.assertNotIn("时序算术", surfaces[README_ZH])
        self.assertNotRegex(
            surfaces[README_EN].lower(), r"timing[- ]arithmetic"
        )
        for path in (README_EN, TIMING_ADR, notebook_path):
            text = surfaces[path].lower()
            with self.subTest(reference_language=path.relative_to(ROOT)):
                self.assertIn("adjusted reference arithmetic", text)
                self.assertIn("next-session tradability is not verified", text)
                self.assertIn("not an execution or backtest", text)

    def test_database_evidence_distinguishes_bounded_selectors_from_open_work(self) -> None:
        bounded_evidence = (
            "ClickHouse 24.8.14.39",
            "fresh old-key full schemas",
            "four source rows in one old-key part",
            "create-copy-EXCHANGE",
            "old-key backup",
            "OPTIMIZE FINAL",
            "Postgres 16",
            "PostgreSQL array binding",
            "`DISTINCT ON`",
        )
        open_work = (
            "query plans",
            "cross-store transactions",
            "CI does not run database integration",
        )
        for document in (README_ZH, README_EN, SNAPSHOT_ADR):
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(ROOT)):
                for marker in bounded_evidence + open_work:
                    self.assertIn(marker, text)

    def test_public_site_uses_evidence_boundaries_not_maturity_claims(self) -> None:
        pages = (
            ROOT / "docs" / "index.html",
            ROOT / "docs" / "assets" / "preview-board.html",
        )
        required = (
            "Synthetic fixtures",
            "Unit-verified",
            "Bounded local selectors",
            "Real integration pending",
        )
        for page in pages:
            text = page.read_text(encoding="utf-8")
            with self.subTest(page=page.relative_to(ROOT)):
                for marker in required:
                    self.assertIn(marker, text)
                self.assertNotIn("2026-07-30", text)
                self.assertNotRegex(text, r"(?:92|88|84|38)%")
                self.assertNotIn("Verified Engineering Signals", text)
                self.assertNotIn("verified locally", text.lower())
                self.assertNotIn("Smoke tested", text)
                self.assertNotIn("zero-cost", text.lower())

    def test_legacy_report_is_short_inventory_not_current_evidence(self) -> None:
        text = INTEGRATION_REPORT.read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 100)
        self.assertNotIn("## Current bounded evidence", text)
        self.assertNotIn("## Current commands", text)
        self.assertNotRegex(text, r"(?m)^python3\s+")
        lower_text = text.lower()
        for marker in (
            "Historical/legacy inventory",
            "not current verification evidence",
            "README.md",
            "README_EN.md",
            "Postgres 16",
            "ClickHouse 24.8.14.39",
            "real integration pending",
        ):
            self.assertIn(marker.lower(), lower_text)

    def test_public_documents_do_not_publish_dynamic_run_counts(self) -> None:
        patterns = (
            re.compile(r"\bRan\s+\d+\s+tests?\b", flags=re.IGNORECASE),
            re.compile(r"\b\d+\s+(?:tests?\s+(?:passed|passing)|个测试(?:通过)?)", flags=re.IGNORECASE),
            re.compile(
                r"\b[A-Za-z_]*(?:count|markers|html_bytes|rows|lines)\s*=\s*\d+",
                flags=re.IGNORECASE,
            ),
        )
        for path in _public_documents():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                for pattern in patterns:
                    self.assertIsNone(pattern.search(text), pattern.pattern)

    def test_public_notebook_is_valid_json(self) -> None:
        notebook_path = NOTEBOOK if NOTEBOOK.exists() else OLD_NOTEBOOK
        payload = json.loads(notebook_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["nbformat"], 4)

    def test_public_contract_states_versioned_factor_boundary_and_snapshot_formula(self) -> None:
        surfaces = {
            README_ZH: README_ZH.read_text(encoding="utf-8"),
            README_EN: README_EN.read_text(encoding="utf-8"),
            NOTEBOOK: NOTEBOOK.read_text(encoding="utf-8"),
            ROOT / "docs" / "index.html": (
                ROOT / "docs" / "index.html"
            ).read_text(encoding="utf-8"),
        }
        for path, text in surfaces.items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("latest", text)
                self.assertIn("asof", text.lower().replace("as-of", "asof"))
                self.assertIn("vintage", text)
                self.assertNotIn("Pull point-in-time factor values", text)

        for path in (README_ZH, README_EN):
            with self.subTest(snapshot_formula=path.relative_to(ROOT)):
                self.assertIn(
                    "close_adjusted = close_raw * adjustment_factor",
                    surfaces[path],
                )

        api_contract = (ROOT / "api-contract.md").read_text(encoding="utf-8")
        self.assertIn("| `query_mode` | string | 否 | `latest` | `latest`、`asof` 或 `vintage` |", api_contract)
        self.assertIn("| `asof_time` | string | 条件必填 | `null` |", api_contract)
        self.assertIn("| `data_version` | string | 条件必填 | `null` |", api_contract)
        self.assertNotIn("当前只支持 `latest`", api_contract)


if __name__ == "__main__":
    unittest.main()
