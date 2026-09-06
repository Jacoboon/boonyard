"""PHASE_2.md's rule: ``adapter.py`` is the only file in the SaaS layer that touches
``boonyard.*``. Enforced by grep, as the order asks (§1, §3), so the web layer can
never drift ahead of the package through a scattered import.
"""

import re
import unittest
from pathlib import Path

SAAS_DIR = Path(__file__).resolve().parents[1]
_IMPORT_RE = re.compile(r"^\s*(?:import\s+boonyard\b|from\s+boonyard\b)", re.MULTILINE)


class AdapterOnlyRuleTests(unittest.TestCase):
    def _offenders(self) -> list[str]:
        hits = []
        for path in sorted(SAAS_DIR.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if _IMPORT_RE.search(path.read_text(encoding="utf-8")):
                hits.append(path.relative_to(SAAS_DIR).as_posix())
        return hits

    def test_boonyard_is_imported_in_adapter_only(self):
        self.assertEqual(self._offenders(), ["boonyardnn/adapter.py"])

    def test_the_grep_actually_sees_the_adapter(self):
        # Guard against a silently-passing regex: the adapter must be found.
        self.assertIn("boonyardnn/adapter.py", self._offenders())
