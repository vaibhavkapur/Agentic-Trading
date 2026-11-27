"""Expanding walk-forward selection and paired synthetic policy comparisons."""
import csv
import json
import math
import random
import statistics
from dataclasses import replace

from .environment import AllocationEnv, MarketRules
from .market import ContractError
from .policy import artifact, load_policy, train


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def record(path, event):
    with path.open("a") as stream:
        stream.write(json.dumps(event, allow_nan=False) + "\n")


def validate_config(cfg):
    if cfg["schema"] != "allocation-experiment/v1" or type(cfg["seed"]) is not int:
        raise ContractError("config", "Unsupported configuration or seed")
    for key in ("initial_train_steps", "validation_steps", "test_steps", "episodes", "bootstrap_samples"):
        if type(cfg[key]) is not int or cfg[key] < 1:
            raise ContractError("budget", f"{key} must be a positive integer")
    if not cfg["learning_rates"] or not all(0 < x <= 1 for x in cfg["learning_rates"]):
        raise ContractError("rates", "Learning rates must be in (0, 1]")
    if not all(0 <= cfg[key] <= 1 for key in ("discount", "epsilon")):
        raise ContractError("learning", "Invalid discount or exploration probability")
    return MarketRules(**cfg["rules"])


def windows(length, cfg):
    train_end = cfg["initial_train_steps"]
    while train_end + cfg["validation_steps"] + cfg["test_steps"] < length:
        validation_end = train_end + cfg["validation_steps"]
        test_end = validation_end + cfg["test_steps"]
        yield train_end, validation_end, test_end
        train_end += cfg["test_steps"]


def rollout(env, choose, on_step=None):
    state, initial = env.reset()
    peak = initial["equity"]
    drawdown = costs = turnover = 0.0
    previous = peak
    partials = 0
    rewards = []
    while True:
        action = choose(state)
        state, reward, done, _, info = env.step(action)
        rewards.append(reward)
        costs += info["fee"] + info["slippage"]
        turnover += info["notional"] / previous
        partials += int(abs(info["requested_shares"] - info["filled_shares"]) > 1e-8)
        previous = info["equity"]
        peak = max(peak, previous)
        drawdown = max(drawdown, 1 - previous / peak)
        if on_step:
            on_step(dict(action=action, reward=reward, **info))
        if done:
            break
    return dict(net_return=previous / initial["equity"] - 1, max_drawdown=drawdown,
                daily_log_vol=statistics.pstdev(rewards), cost_usd=costs, turnover=turnover,
                partial_fills=partials, steps=len(rewards))


def scenarios(bars, start, end, rules):
    yield "base", bars, rules
    yield "double_cost", bars, replace(rules, fee_bps=2 * rules.fee_bps,
                                       slippage_bps=2 * rules.slippage_bps)
    # Apply a widening selloff only to held-out prices. Preserve historical observations.
    shocked = list(bars[:start + 1])
    for n, bar in enumerate(bars[start + 1:end + 1], 1):
        scale = 0.92 * 0.997 ** (n - 1)
        shocked.append(replace(bar, open_usd=bar.open_usd * scale,
                               close_usd=bar.close_usd * scale * 0.997,
                               auction_shares=bar.auction_shares * 0.25))
    yield "selloff_thin_auction", tuple(shocked), rules


def interval(values, samples, seed):
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [means[math.floor(0.025 * (samples - 1))], means[math.ceil(0.975 * (samples - 1))]]


def summarize(results, samples, seed):
    groups = {}
    for row in results:
        groups.setdefault((row["scenario"], row["policy"]), {})[row["fold"]] = row
    summary = []
    for (scenario, policy), folds in groups.items():
        returns = [v["net_return"] for v in folds.values()]
        paired = [value - groups[(scenario, "buy_hold")][fold]["net_return"]
                  for fold, value in zip(folds, returns)]
        summary.append(dict(scenario=scenario, policy=policy, folds=len(folds),
                            mean_return=statistics.mean(returns), return_ci95=interval(returns, samples, seed),
                            mean_excess_buy_hold=statistics.mean(paired), excess_ci95=interval(paired, samples, seed),
                            worst_drawdown=max(v["max_drawdown"] for v in folds.values())))
    return summary


def experiment(bars, cfg, out, provenance):
    rules = validate_config(cfg)
    splits = list(windows(len(bars), cfg))
    if not splits:
        raise ContractError("split", "Insufficient sessions for a complete walk-forward fold")
    results = []
    journal = out / "runs.jsonl"
    with (out / "decisions.csv").open("w", newline="") as stream:
        writer = None
        for fold, (train_end, val_end, test_end) in enumerate(splits, 1):
            seed = cfg["seed"] + fold
            boundaries = {key: bars[i].closed.isoformat() for key, i in
                          (("train_start", 0), ("train_end", train_end),
                           ("validation_end", val_end), ("test_end", test_end))}
            candidates = []
            for candidate, alpha in enumerate(cfg["learning_rates"]):
                run = dict(fold=fold, candidate=candidate, alpha=alpha, seed=seed, **boundaries)
                record(journal, dict(event="train_started", **run))
                env = AllocationEnv(bars[:train_end + 1], rules)
                policy, scores = train(env, seed, cfg["episodes"], alpha, cfg["discount"], cfg["epsilon"])
                val = rollout(AllocationEnv(bars[:val_end + 1], rules, train_end), policy.__getitem__)
                record(journal, dict(event="validated", episode_returns=scores, metrics=val,
                                     training_steps=train_end * len(scores), **run))
                candidates.append((val["net_return"], policy, candidate))
            validation, policy, candidate = max(candidates, key=lambda c: c[0])
            meta = dict(**provenance, fold=fold, candidate=candidate, seed=seed,
                        validation_return=validation, **boundaries)
            payload = artifact(policy, meta)
            write_json(out / f"policy-fold-{fold}.json", payload)
            selected = load_policy(payload)
            for scenario, path, costs in scenarios(bars[:test_end + 1], val_end, test_end, rules):
                rng = random.Random(seed)
                choices = dict(q_learning=selected.__getitem__, cash=lambda _: 0,
                               buy_hold=lambda _: 2, random=lambda _: rng.randrange(3))
                for name, choose in choices.items():
                    tags = dict(fold=fold, scenario=scenario, policy=name)

                    def save(step):
                        nonlocal writer
                        row = dict(**tags, **step)
                        if writer is None:
                            writer = csv.DictWriter(stream, fieldnames=list(row), lineterminator="\n")
                            writer.writeheader()
                        writer.writerow(row)

                    metrics = rollout(AllocationEnv(path, costs, val_end, test_end), choose, save)
                    results.append(dict(**tags, **metrics))
            record(journal, dict(event="fold_complete", **meta))
    summary = summarize(results, cfg["bootstrap_samples"], cfg["seed"])
    write_json(out / "metrics.json", results)
    write_json(out / "summary.json", summary)
    write_json(out / "paper-policy.json", payload)
    lines = ["# Synthetic allocation policy report", "",
             f"{len(splits)} expanding folds, each with {cfg['test_steps']} held-out daily returns. "
             f"Each policy started every window in cash with USD {rules.initial_cash:,.0f}.",
             "", "Mean net return and worst peak-to-trough drawdown are per test window. "
             "Intervals resample whole test folds with replacement. Excess return is paired "
             "by fold against buy-and-hold. Few folds and serial dependence limit precision.",
             "", "| Scenario | Policy | Mean return (95% interval) | Excess vs hold (95% interval) | Worst drawdown |",
             "|---|---|---:|---:|---:|"]
    for row in summary:
        lo, hi = row["return_ci95"]
        elo, ehi = row["excess_ci95"]
        lines.append(f"| {row['scenario']} | {row['policy']} | {row['mean_return']:.2%} "
                     f"({lo:.2%}, {hi:.2%}) | {row['mean_excess_buy_hold']:.2%} "
                     f"({elo:.2%}, {ehi:.2%}) | {row['worst_drawdown']:.2%} |")
    lines += ["", "The final export is the last fold’s validation-selected policy. "
              "All candidate scores, including losing runs, are in `runs.jsonl`. "
              "The fixture and stress paths are synthetic. Results describe these simulations only."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
