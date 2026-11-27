"""Versioned wire contracts and deterministic point-in-time canonicalization."""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

LABELS = ("negative", "neutral", "positive", "uncertain")
VERSION = "sentiment.v1"


class Invalid(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value
    ):
        raise Invalid("invalid_timestamp", "Expected an ISO 8601 UTC instant ending in Z")
    try:
        return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise Invalid("invalid_timestamp", "Invalid UTC date or time") from exc


def stamp(dt):
    return dt.isoformat().replace("+00:00", "Z")


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Article:
    id: str
    source: str
    event_at: datetime
    available_at: datetime
    headline: str
    body: str

    @classmethod
    def parse(cls, row):
        fields = {"id", "source", "event_at", "available_at", "headline", "body", "schema_version"}
        if not isinstance(row, dict) or set(row) != fields or row["schema_version"] != VERSION:
            raise Invalid("invalid_article", "Article fields or schema version are invalid")
        for key in ("id", "source", "headline", "body"):
            value = row[key]
            if not isinstance(value, str) or len(value) > 65536 or (key != "body" and not value.strip()):
                raise Invalid("invalid_article", f"Invalid {key}")
        event, available = instant(row["event_at"]), instant(row["available_at"])
        if available < event:
            raise Invalid("invalid_chronology", "Availability precedes publication")
        return cls(row["id"], row["source"], event, available, row["headline"], row["body"])

    @property
    def fingerprint(self):
        return digest([normalize(self.headline), normalize(self.body)])


def canonicalize(articles):
    by_id, by_content, copies = {}, {}, {}
    for article in sorted(articles, key=lambda a: (a.available_at, a.id)):
        if article.id in by_id and article != by_id[article.id]:
            raise Invalid("conflicting_id", f"Conflicting immutable ID {article.id}")
        by_id[article.id] = article
        original = by_content.setdefault(article.fingerprint, article)
        if original.id != article.id:
            copies[article.id] = original.id
    return list(by_content.values()), copies


@dataclass(frozen=True)
class Mention:
    issuer: str
    headline: str
    body: str
    shared_clause: bool


class Linker:
    def __init__(self, issuers):
        self.aliases = {}
        for issuer, names in issuers.items():
            for name in names:
                self.aliases.setdefault(normalize(name), set()).add(issuer)
        variants = sorted(self.aliases, key=len, reverse=True)
        self.pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, variants)) + r")(?!\w)")

    def link(self, article):
        sections = [normalize(article.headline), normalize(article.body)]
        targets, uncertain, issues = {}, set(), set()
        aliases = [m.group() for section in sections for m in self.pattern.finditer(section)]
        unambiguous = {next(iter(self.aliases[a])) for a in aliases if len(self.aliases[a]) == 1}
        ambiguous = any(len(self.aliases[a]) > 1 for a in aliases)
        for index, section in enumerate(sections):
            for clause in re.split(r"[.!?;]|\b(?:while|whereas|but)\b", section):
                names = self.pattern.findall(clause)
                if any(len(self.aliases[name]) > 1 for name in names):
                    issues.add("ambiguous_alias")
                    continue
                ids = {next(iter(self.aliases[name])) for name in names}
                if not ids and len(unambiguous) == 1 and not ambiguous:
                    ids = unambiguous
                if len(ids) > 1:
                    uncertain.update(ids)
                for issuer in ids:
                    text = self.pattern.sub(" ", clause).strip(" ,")
                    targets.setdefault(issuer, [[], []])[index].append(text)
        if not targets and not issues:
            issues.add("unlinked")
        mentions = [Mention(k, " ".join(v[0]), " ".join(v[1]), k in uncertain)
                    for k, v in sorted(targets.items())]
        return mentions, sorted(issues)
