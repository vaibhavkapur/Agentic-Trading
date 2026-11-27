"""Local index adapters. All statistics at query time use eligible passages only."""
import hashlib
import math
import re
from collections import Counter
from functools import lru_cache


ALIASES = {"sales": "revenue", "turnover": "revenue", "capex": "capital_expenditure",
           "earnings": "income", "liquidity": "cash", "forecast": "outlook"}
STOP = set("the of was is in by a an its what how did does for across sources compare reported".split())


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


def chunks(body, limit):
    """Prefer paragraph and sentence boundaries, hard-wrap oversized runs."""
    for para in re.finditer(r"[^\n]+", body):
        start, end = para.span()
        while start < end:
            stop = min(start + limit, end)
            if stop < end:
                boundary = body.rfind(". ", start, stop)
                if boundary <= start:
                    boundary = body.rfind(" ", start, stop)
                if boundary > start:
                    stop = boundary + 1
            raw = body[start:stop]
            if raw.strip():
                left = start + len(raw) - len(raw.lstrip())
                right = start + len(raw.rstrip())
                yield left, right, body[left:right]
            start = stop


@lru_cache(maxsize=8192)
def direction(term, dimensions):
    bits = hashlib.shake_256(term.encode()).digest((dimensions + 7) // 8)
    return tuple(1 if bits[i // 8] & (1 << (i % 8)) else -1 for i in range(dimensions))


def dense(text, dimensions):
    words = tokens(text.lower().replace("capital expenditure", "capex"))
    counts = Counter(ALIASES.get(w, w) for w in words)
    vector = [0.0] * dimensions
    for word, count in sorted(counts.items()):
        weight = 1 + math.log(count)
        for i, sign in enumerate(direction(word, dimensions)):
            vector[i] += weight * sign
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def rank(query, candidates, config, k):
    if not candidates:
        return []
    words = set(tokens(query))
    if not words:
        return []
    query_vec = dense(query, config["dimensions"])
    n = len(candidates)
    df = Counter(term for row in candidates for term in row["terms"] if term in words)
    avg = sum(sum(r["terms"].values()) for r in candidates) / n or 1
    for row in candidates:
        counts = row["terms"]
        length = sum(counts.values())
        bm25 = 0.0
        for term in sorted(words.intersection(counts)):
            freq = counts[term]
            idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
            bm25 += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * length / avg))
        row["keyword"] = bm25
        row["dense"] = sum(a * b for a, b in zip(query_vec, row["vector"]))
    # Reciprocal rank fusion followed by a weighted lexical-coverage reranker.
    fused = Counter()
    for channel, weight in (("keyword", config["keyword_weight"]), ("dense", 1-config["keyword_weight"])):
        ordered = sorted(candidates, key=lambda r: (-r[channel], r["chunk_id"]))
        for position, row in enumerate((r for r in ordered if r[channel] > 0), 1):
            fused[row["chunk_id"]] += weight * 21 / (20 + position)
    pool = sorted((r for r in candidates if r["chunk_id"] in fused),
                  key=lambda r: (-fused[r["chunk_id"]], r["chunk_id"]))[:config["candidate_limit"]]
    for row in pool:
        coverage = len(words.intersection(row["terms"])) / len(words)
        row["score"] = round(0.6 * fused[row["chunk_id"]] + 0.4 * coverage, 8)
    return sorted(pool, key=lambda r: (-r["score"], r["chunk_id"]))[:k]
