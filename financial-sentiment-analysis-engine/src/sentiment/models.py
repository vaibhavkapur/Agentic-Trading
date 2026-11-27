"""Deterministic in-domain baselines, calibration and selective prediction."""
import math
import re
from collections import Counter

from .domain import LABELS


def words(text):
    return re.findall(r"[a-z]+", text)


def features(mention):
    tokens = []
    for section in (mention.headline, mention.body):
        parts = words(section)
        tokens.extend(parts)
        tokens.extend(a + "_" + b for a, b in zip(parts, parts[1:]))
    return tokens


def softmax(logits, temperature=1.0):
    peak = max(logits)
    weights = [math.exp((v - peak) / temperature) for v in logits]
    total = sum(weights)
    return [weight / total for weight in weights]


def nll(pairs):
    return -sum(math.log(max(p[LABELS.index(label)], 1e-15)) for p, label in pairs) / len(pairs)


class Classifier:
    def __init__(self, training):
        self.counts = {label: Counter() for label in LABELS}
        counts = Counter()
        self.vocab = set()
        for mention, label in training:
            tokens = features(mention)
            self.counts[label].update(tokens)
            self.vocab.update(tokens)
            counts[label] += 1
        if set(counts) != set(LABELS):
            raise ValueError("Training needs examples of every class")
        self.prior = [counts[label] / len(training) for label in LABELS]
        self.norm = {k: sum(c.values()) + len(self.vocab) for k, c in self.counts.items()}

    def logits(self, mention):
        tokens = [t for t in features(mention) if t in self.vocab]
        return [math.log(prior) + sum(math.log((1 + self.counts[label][t]) / self.norm[label])
                                     for t in tokens)
                for label, prior in zip(LABELS, self.prior)]

    def calibrate(self, validation, grid):
        scores = [(self.logits(m), y) for m, y in validation]
        trials = [(t, nll([(softmax(s, t), y) for s, y in scores])) for t in grid]
        return min(trials, key=lambda item: (item[1], abs(item[0] - 1)))[0], trials


class Lexicon:
    def __init__(self, config):
        self.pos, self.neg = set(config["positive"]), set(config["negative"])
        self.hedges, self.sarcasm = set(config["uncertainty"]), config["sarcasm"]

    def polarity(self, text):
        tokens = words(text)
        total = 0
        for i, token in enumerate(tokens):
            sign = int(token in self.pos) - int(token in self.neg)
            if i and tokens[i - 1] in {"not", "never"}:
                sign *= -1
            total += sign
        return total

    def assess(self, mention):
        text = mention.headline + " " + mention.body
        head, body = self.polarity(mention.headline), self.polarity(mention.body)
        reason = None
        if mention.shared_clause:
            reason = "shared_clause"
        elif any(cue in text for cue in self.sarcasm):
            reason = "sarcasm_cue"
        elif head * body < 0:
            reason = "headline_body_conflict"
        elif self.hedges.intersection(words(text)):
            reason = "explicit_uncertainty"
        net = head + body
        logits = [-net, 1.0 if net == 0 else 0.0, net, 0.0]
        if reason:
            logits = [0, 0, 0, 2]
        return softmax(logits), reason


def decision(probs, reason, threshold):
    label = LABELS[probs.index(max(probs))]
    if not reason and label == "uncertain":
        reason = "uncertain_class"
    if not reason and max(probs) < threshold:
        reason = "low_confidence"
    return ("uncertain" if reason else label), reason
