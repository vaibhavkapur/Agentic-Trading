import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.domain import ROOT
from research.ingest import ingest
from research.store import connect, initialize
from research.workflow import research

MANIFEST = ROOT / "data/fixtures/manifest.json"
AS_OF = "2025-03-15T00:00:00Z"


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.path = self.base / "research.sqlite"
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        initialize(self.db)
        ingest(self.db, MANIFEST)

    def query(self, **changes):
        return research(self.db, dict(dict(subject="ALDR", metrics=["revenue"], period="FY2024", as_of=AS_OF), **changes))

    def inject_manifest(self, transform, raw=None):
        source = json.loads(MANIFEST.read_text())["documents"][0]
        data = raw if raw is not None else (MANIFEST.parent / source["path"]).read_bytes()
        (self.base / "report.txt").write_bytes(data)
        m = dict(source, id="extra", series="extra", path="report.txt", sha256=hashlib.sha256(data).hexdigest())
        transform(m)
        path = self.base / "manifest.json"
        path.write_text(json.dumps({"version": 1, "documents": [m]}))
        return path
