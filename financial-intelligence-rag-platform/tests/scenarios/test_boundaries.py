from finrag.domain import Principal
from tests.support import Corpus, OTHER, PRIVATE, PUBLIC


class Boundaries(Corpus):
    def test_cross_tenant_and_group_retrieval_and_resolution(self):
        for reader, doc, query in (
            (OTHER, "other-fund", "What was Aster Grid's operating income in FY2024?"),
            (PRIVATE, "aster-private", "What was Aster Grid's capital expenditure in FY2024?"),
        ):
            restricted = self.ask(query, principal=reader)["claims"][0]["citation"]
            self.assertEqual(restricted["doc_id"], doc)
            self.hidden(restricted)
            self.assertEqual(self.ask(query, op="search", filters={"doc_id": doc})["hits"], [])
            self.assertEqual(self.ask(query)["status"], "abstained")
        self.assertEqual(self.ask(op="search", principal=Principal(PUBLIC.tenant, ()))["hits"], [])

    def test_stale_filing_superseded_at_exact_availability(self):
        early = "2025-03-03T08:59:59.999999Z"
        later = "2025-03-03T09:00:00Z"
        first = self.ask(as_of=early, filters={"kind": "filing"})["claims"][0]["citation"]
        second = self.ask(as_of=later, filters={"kind": "filing"})["claims"][0]["citation"]
        self.assertEqual((first["version"], second["version"]), (1, 2))
        self.assertEqual(self.resolve(first, as_of=early), first)
        self.hidden(first, as_of=later)
        self.hidden(second, as_of=early)

    def test_future_document_leakage(self):
        early = "2025-02-10T08:59:59Z"
        self.assertEqual(self.ask(as_of=early, op="search", filters={"period":"FY2024"})["hits"], [])
        self.assertEqual(self.ask(as_of=early)["status"], "abstained")

    def test_malicious_embedded_instructions_are_inert(self):
        search = self.ask("ignore previous instructions", op="search", filters={"doc_id":"tampered-note"})
        self.assertIn("Ignore all previous", search["hits"][0]["passage"])
        result = self.ask("What was Aster Grid's net income in FY2024?", filters={"doc_id":"tampered-note"})
        self.assertEqual(result["claims"], [])
        result = self.ask("What was Aster Grid's net income in FY2024?")
        self.assertEqual([c["value"] for c in result["claims"]], ["USD 10 million"])

    def test_unanswerable_and_compound_questions(self):
        for query in ("What was Aster Grid's operating income in FY2023?",
                      "What was Aster Grid's revenue in FY2024 and who signed it?",
                      "Predict Aster Grid's share price next week"):
            result = self.ask(query)
            self.assertEqual((result["status"], result["claims"]), ("abstained", []))

    def test_deletion_propagates_to_all_as_of_dates(self):
        self.db = self.folder / "before.db"
        self.build(dict(self.history, events=self.history["events"][:-1]))
        query = "What was Aster Grid's operating cash flow in FY2024?"
        as_of = "2025-02-20T00:00:00Z"
        ref = self.ask(query, as_of=as_of)["claims"][0]["citation"]
        self.assertEqual(self.resolve(ref, as_of=as_of), ref)
        self.build(self.history)
        self.hidden(ref, as_of=as_of)
        self.assertEqual(self.ask(query, as_of=as_of)["claims"], [])
        self.assertEqual(self.ask(query, op="search", filters={"doc_id":"retired"})["hits"], [])
