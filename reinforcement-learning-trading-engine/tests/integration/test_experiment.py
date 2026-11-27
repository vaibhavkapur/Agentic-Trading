import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, flat
from trading_engine.environment import AllocationEnv, MarketRules
from trading_engine.evaluation import rollout, windows
from trading_engine.market import ContractError, load_fixture
from trading_engine.policy import load_policy


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.cfg = json.loads((ROOT / "config/demo.json").read_text())
        self.cfg.update(initial_train_steps=210, validation_steps=50, test_steps=50,
                        episodes=2, bootstrap_samples=30)
        self.config = self.work / "config.json"
        self.config.write_text(json.dumps(self.cfg))

    def demo(self, name, *args, check=True):
        return subprocess.run([sys.executable, str(ROOT / "scripts/demo.py"), "--out",
                               str(self.work / name), "--config", str(self.config), *args],
                              check=check, capture_output=True, text=True)

    def test_end_to_end_identical_scenarios_and_export_replay(self):
        self.demo("trial")
        out = self.work / "trial"
        bars = load_fixture(ROOT / "data/fixtures")
        splits = list(windows(len(bars), self.cfg))
        self.assertEqual(splits, [(210, 260, 310), (260, 310, 360)])
        with (out / "decisions.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 2 * 3 * 4 * 50)
        for fold, (_, val_end, test_end) in enumerate(splits, 1):
            expected = [bar.closed.isoformat() for bar in bars[val_end + 1:test_end + 1]]
            for scenario in ("base", "double_cost", "selloff_thin_auction"):
                for name in ("q_learning", "cash", "random", "buy_hold"):
                    times = [r["time"] for r in rows if (r["fold"], r["scenario"], r["policy"])
                             == (str(fold), scenario, name)]
                    self.assertEqual(times, expected)
        payload = json.loads((out / "paper-policy.json").read_text())
        selected = load_policy(payload)
        replay = []
        metrics = rollout(AllocationEnv(bars, MarketRules(**self.cfg["rules"]), 310, 360),
                          selected.__getitem__, replay.append)
        recorded = [r for r in rows if (r["fold"], r["scenario"], r["policy"]) == ("2", "base", "q_learning")]
        self.assertEqual([r["action"] for r in replay], [int(r["action"]) for r in recorded])
        scores = json.loads((out / "metrics.json").read_text())
        self.assertEqual(metrics["net_return"], next(r["net_return"] for r in scores if
                         (r["fold"], r["scenario"], r["policy"]) == (2, "base", "q_learning")))
        log = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
        for fold, (train_end, _, _) in enumerate(splits, 1):
            candidates = [e for e in log if e["event"] == "validated" and e["fold"] == fold]
            best = max(candidates, key=lambda r: r["metrics"]["net_return"])
            exported = json.loads((out / f"policy-fold-{fold}.json").read_text())
            self.assertEqual(best["candidate"], exported["provenance"]["candidate"])
            self.assertTrue(all(e["training_steps"] == train_end * 2 for e in candidates))
        self.assertEqual(log[-1]["event"], "experiment_complete")
        self.demo("repeat")
        for path in out.iterdir():
            self.assertEqual(path.read_bytes(), (self.work / "repeat" / path.name).read_bytes())
        self.assertNotEqual(self.demo("trial", check=False).returncode, 0)
        for changes in (dict(mode="live"), dict(actions=[3] * 45), dict(actions=[])):
            with self.assertRaises(ContractError):
                load_policy(dict(payload, **changes))

    def test_fixture_tampering_logs_failure_and_stops(self):
        folder = self.work / "fixtures"
        shutil.copytree(ROOT / "data/fixtures", folder)
        with (folder / "sessions.csv").open("a") as stream:
            stream.write("\n")
        result = self.demo("bad", "--fixture", str(folder), check=False)
        self.assertNotEqual(result.returncode, 0)
        entry = json.loads((self.work / "bad/runs.jsonl").read_text())
        self.assertEqual((entry["event"], entry["code"]), ("experiment_failed", "digest"))
        self.assertFalse((self.work / "bad/paper-policy.json").exists())

    def test_short_window_is_logged(self):
        self.cfg["initial_train_steps"] = 400
        self.config.write_text(json.dumps(self.cfg))
        self.assertNotEqual(self.demo("short", check=False).returncode, 0)
        self.assertEqual(json.loads((self.work / "short/runs.jsonl").read_text())["code"], "split")

    @unittest.skipUnless(importlib.util.find_spec("gymnasium"), "install requirements-gym.txt for checker")
    def test_gymnasium_contract_and_seeded_actions(self):
        from gymnasium.utils.env_checker import check_env
        from trading_engine.gym_adapter import GymAllocationEnv
        env = GymAllocationEnv(flat(12))
        check_env(env, skip_render_check=True)
        env.reset(seed=9)
        actions = [env.action_space.sample() for _ in range(5)]
        env.reset(seed=9)
        self.assertEqual(actions, [env.action_space.sample() for _ in range(5)])
