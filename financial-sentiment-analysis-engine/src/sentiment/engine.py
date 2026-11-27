"""Local file adapter and immutable research snapshot."""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .domain import Article, Invalid, LABELS, Linker, Mention, VERSION, canonicalize, digest, instant, stamp
from .models import Classifier, Lexicon, decision, softmax


def read_lines(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                yield json.loads(line)
            except ValueError as exc:
                raise Invalid("invalid_json", f"{path.name} line {number}") from exc


@dataclass(frozen=True)
class Sample:
    article: Article
    mention: Mention
    label: str
    annotated_at: datetime


class Catalog:
    def __init__(self, articles, linker):
        self.articles, self.copies = canonicalize(articles)
        self.mentions, self.issues = {}, {}
        for article in self.articles:
            self.mentions[article.id], self.issues[article.id] = linker.link(article)

    @classmethod
    def load(cls, path, linker):
        return cls([Article.parse(row) for row in read_lines(path)], linker)


class Engine:
    def __init__(self, config, articles, annotations):
        if config.get("schema_version") != VERSION:
            raise Invalid("invalid_config", "Unsupported config schema")
        if not 0 <= config["minimum_confidence"] <= 1 or config["window_hours"] <= 0:
            raise Invalid("invalid_config", "Invalid confidence or window size")
        if not config["temperature_grid"] or any(t <= 0 for t in config["temperature_grid"]):
            raise Invalid("invalid_config", "Calibration needs positive temperature candidates")
        self.config = config
        self.bounds = [instant(config[k]) for k in ("train_until", "calibrate_until", "test_until")]
        if not self.bounds[0] < self.bounds[1] < self.bounds[2]:
            raise Invalid("invalid_split", "Split boundaries must increase")
        self.ready = self.bounds[1]
        self.linker = Linker(config["issuers"])
        self.reference = Catalog(articles, self.linker)
        self.splits = {"train": [], "calibration": [], "test": []}
        self.delayed_labels = []
        self._partition(annotations)
        train = [(s.mention, s.label) for s in self.splits["train"]]
        calibration = [(s.mention, s.label) for s in self.splits["calibration"]]
        if not calibration:
            raise Invalid("empty_calibration", "Calibration needs labeled records")
        self.classifier = Classifier(train)
        self.lexicon = Lexicon(config)
        self.temperature, self.trials = self.classifier.calibrate(calibration, config["temperature_grid"])
        fit_records = [(s.article.id, s.article.fingerprint, stamp(s.article.available_at),
                        s.mention.issuer, s.label, stamp(s.annotated_at))
                       for name in ("train", "calibration") for s in self.splits[name]]
        code = [hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest()
                for f in ("domain.py", "models.py", "engine.py")]
        self.version = digest([config, sorted(fit_records), code])
        self.input_version = digest([(a.id, a.fingerprint, a.source, stamp(a.event_at),
                                      stamp(a.available_at)) for a in articles])

    def _partition(self, annotations):
        lookup = {(a.id, m.issuer): (a, m) for a in self.reference.articles for m in self.reference.mentions[a.id]}
        seen = set()
        for row in annotations:
            if not isinstance(row, dict) or set(row) != {"article_id", "issuer", "label", "rule", "annotated_at"}:
                raise Invalid("invalid_annotation", "Unexpected annotation schema")
            key = (row["article_id"], row["issuer"])
            if key not in lookup or key in seen or row["label"] not in LABELS or not row["rule"]:
                raise Invalid("invalid_annotation", f"Invalid or repeated annotation {key}")
            seen.add(key)
            article, mention = lookup[key]
            annotated = instant(row["annotated_at"])
            if annotated < article.available_at:
                raise Invalid("invalid_annotation_time", f"Label predates availability {key}")
            for name, end in zip(self.splits, self.bounds):
                if article.available_at < end:
                    if annotated < end:
                        self.splits[name].append(Sample(article, mention, row["label"], annotated))
                    else:
                        self.delayed_labels.append(key)
                    break
        for rows in self.splits.values():
            rows.sort(key=lambda s: (s.article.available_at, s.article.id, s.mention.issuer))

    @classmethod
    def load(cls, root):
        path = root / "data/fixtures"
        return cls(json.loads((root / "config/v1.json").read_text()),
                   [Article.parse(row) for row in read_lines(path / "articles.jsonl")],
                   list(read_lines(path / "annotations.jsonl")))

    def score(self, article, mention):
        logits = self.classifier.logits(mention)
        probs = softmax(logits, self.temperature)
        _, guard = self.lexicon.assess(mention)
        label, reason = decision(probs, guard, self.config["minimum_confidence"])
        return dict(article_id=article.id, issuer=mention.issuer, source=article.source,
                    event_at=stamp(article.event_at), available_at=stamp(article.available_at),
                    label=label, abstain_reason=reason, probabilities=dict(zip(LABELS, probs)),
                    sentiment=None if reason else probs[2] - probs[0])

    def feed(self, as_of, window_end, issuer=None, catalog=None):
        catalog = self.reference if catalog is None else catalog
        if as_of < self.ready:
            raise Invalid("model_unavailable", "Model had not completed calibration at as_of")
        if window_end > as_of:
            raise Invalid("future_window", "Window end must be at or before as_of")
        if issuer is not None and issuer not in self.config["issuers"]:
            raise Invalid("unknown_issuer", "Unknown issuer")
        try:
            start = window_end - timedelta(hours=self.config["window_hours"])
        except OverflowError as exc:
            raise Invalid("invalid_window", "Window exceeds the supported date range") from exc
        rows = []
        for article in catalog.articles:
            if article.available_at > as_of:
                break
            if start <= article.event_at < window_end:
                rows.extend(self.score(article, m) for m in catalog.mentions[article.id]
                            if issuer is None or issuer == m.issuer)
        aggregates = []
        for key in sorted({r["issuer"] for r in rows}):
            group = [r for r in rows if r["issuer"] == key]
            scores = [r["sentiment"] for r in group if r["sentiment"] is not None]
            aggregates.append(dict(issuer=key, article_count=len(group), used_count=len(scores),
                                   abstained_count=len(group) - len(scores),
                                   mean_sentiment=sum(scores) / len(scores) if scores else None,
                                   latest_event_at=stamp(max(instant(r["event_at"]) for r in group)),
                                   latest_input_available_at=stamp(max(instant(r["available_at"]) for r in group))))
        return dict(schema_version=VERSION, model_version=self.version, model_available_at=stamp(self.ready),
                    event_window_start=stamp(start), event_window_end=stamp(window_end),
                    available_at=stamp(as_of), aggregates=aggregates, decisions=rows)
