import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sentiment.domain import Article
from sentiment.engine import Engine, read_lines


def inputs():
    cfg = json.loads((ROOT / "config/v1.json").read_text())
    articles = list(read_lines(ROOT / "data/fixtures/articles.jsonl"))
    labels = list(read_lines(ROOT / "data/fixtures/annotations.jsonl"))
    return cfg, articles, labels


def build(mutate=None):
    cfg, articles, labels = inputs()
    if mutate:
        mutate(articles, labels)
    return Engine(cfg, [Article.parse(a) for a in articles], labels)
