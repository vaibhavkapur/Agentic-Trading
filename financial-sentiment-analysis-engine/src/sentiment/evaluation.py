"""Chronological held-out measurements and raw article-level evidence."""
import math
from collections import Counter
from .domain import LABELS, VERSION, stamp
from .models import features, nll, softmax


def metrics(records):
    if not records:
        raise ValueError("Evaluation requires held-out labels")
    n = len(records)
    confusion = {a: dict.fromkeys(LABELS, 0) for a in LABELS}
    bins = [[] for _ in range(5)]
    brier = 0
    for label, pred, probs in records:
        confusion[label][pred] += 1
        best = probs.index(max(probs))
        bins[min(4, int(max(probs) * 5))].append((max(probs), LABELS[best] == label))
        brier += sum((p - int(k == label)) ** 2 for k, p in zip(LABELS, probs))
    f1 = {}
    for k in LABELS:
        denom = sum(confusion[k].values()) + sum(row[k] for row in confusion.values())
        f1[k] = 2 * confusion[k][k] / denom if denom else 0
    reliability = [dict(count=len(b), confidence=sum(v for v, _ in b) / len(b),
                        accuracy=sum(v for _, v in b) / len(b)) for b in bins if b]
    accuracy = sum(confusion[k][k] for k in LABELS) / n
    z = 1.96
    center = (accuracy + z*z/(2*n)) / (1+z*z/n)
    width = z * math.sqrt(accuracy*(1-accuracy)/n + z*z/(4*n*n)) / (1+z*z/n)
    return dict(n=n, macro_f1=sum(f1.values()) / 4, per_class_f1=f1, accuracy=accuracy,
                accuracy_wilson95=[max(0, center-width), min(1, center+width)],
                brier=brier/n, nll=nll([(p, y) for y, _, p in records]),
                ece=sum(b["count"] * abs(b["accuracy"]-b["confidence"]) for b in reliability)/n,
                reliability_bins=reliability, confusion=confusion,
                coverage=sum(pred != "uncertain" for _, pred, _ in records)/n)


def evaluate(engine):
    groups = {k: [] for k in ("prior", "lexicon", "supervised", "calibrated", "served")}
    evidence = []
    for sample in engine.splits["test"]:
        m = sample.mention
        logits = engine.classifier.logits(m)
        lex, _ = engine.lexicon.assess(m)
        served = engine.score(sample.article, m)
        probs = list(served["probabilities"].values())
        models = [engine.classifier.prior, lex, softmax(logits), probs, probs]
        predictions = {}
        for (name, rows), p in zip(groups.items(), models):
            pred = served["label"] if name == "served" else LABELS[p.index(max(p))]
            rows.append((sample.label, pred, p))
            predictions[name] = dict(label=pred, probabilities=dict(zip(LABELS, p)))
        evidence.append(dict(**served, gold=sample.label, annotated_at=stamp(sample.annotated_at),
                             models=predictions))
    train = engine.splits["train"]
    test = engine.splits["test"]
    proportions = []
    for group in (train, test):
        counts = Counter(s.label for s in group)
        proportions.append([counts[k] / len(group) for k in LABELS])
    divergence = 0.0
    for p, q in zip(*proportions):
        mid = (p + q) / 2
        divergence += sum(v * math.log2(v / mid) / 2 for v in (p, q) if v)
    toks = [t for s in test for t in features(s.mention)]
    issues = {k: v for k, v in engine.reference.issues.items() if v}
    return dict(schema_version=VERSION, model_version=engine.version, input_version=engine.input_version,
                corpus_version=engine.config["corpus_version"], split_counts={k:len(v) for k,v in engine.splits.items()},
                available_cutoffs=[stamp(t) for t in engine.bounds], temperature=engine.temperature,
                calibration_trials=[dict(temperature=t, nll=v) for t,v in engine.trials],
                models={k:metrics(rows) for k,rows in groups.items()},
                drift=dict(test_oov_feature_rate=sum(t not in engine.classifier.vocab for t in toks)/max(1,len(toks)),
                           gold_label_js_bits=divergence),
                canonical_articles=len(engine.reference.articles), duplicates=engine.reference.copies, linking_issues=issues,
                delayed_labels=engine.delayed_labels, test_predictions=evidence)
