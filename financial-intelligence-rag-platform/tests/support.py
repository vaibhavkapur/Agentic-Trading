import json
import shutil
import tempfile
import unittest
from pathlib import Path

from finrag.domain import Fault, Principal
from finrag.service import dispatch
from finrag.store import read_json, rebuild

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/index-v1.json"
NOW = "2025-03-05T12:00:00Z"
PUBLIC = Principal("demo-fund", ("researchers",))
PRIVATE = Principal("demo-fund", ("researchers", "portfolio"))
OTHER = Principal("other-fund", ("researchers",))
QUESTION = "What was Aster Grid's revenue in FY2024?"


class Corpus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        shutil.copytree(ROOT / "data/fixtures", self.folder / "fixtures")
        self.manifest = self.folder / "fixtures/manifest.json"
        self.history = read_json(self.manifest)
        self.db = self.folder / "index.db"
        self.build()

    def build(self, history=None):
        if history is not None:
            self.manifest.write_text(json.dumps(history))
        return rebuild(self.db, self.manifest, CONFIG)

    def ask(self, query=QUESTION, principal=PUBLIC, as_of=NOW, op="answer", **kwargs):
        return dispatch(self.db, principal, op, {"query": query, "as_of": as_of, **kwargs})

    def resolve(self, citation, principal=PUBLIC, as_of=NOW):
        return dispatch(self.db, principal, "resolve", {"as_of": as_of, "chunk_id": citation["chunk_id"]})["citation"]

    def hidden(self, citation, principal=PUBLIC, as_of=NOW):
        with self.assertRaises(Fault) as ctx:
            self.resolve(citation, principal, as_of)
        self.assertEqual(ctx.exception.code, "not_found")
