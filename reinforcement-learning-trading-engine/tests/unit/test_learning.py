import unittest

from support import series
from trading_engine.environment import AllocationEnv, MarketRules
from trading_engine.evaluation import rollout
from trading_engine.policy import train


class LearningTests(unittest.TestCase):
    def test_learns_to_hold_on_a_rising_path_with_zero_cost(self):
        bars = series([(100 + i, 101 + i, 100000) for i in range(60)])
        env = AllocationEnv(bars, MarketRules(fee_bps=0, slippage_bps=0))
        policy, scores = train(env, seed=13, episodes=120, alpha=0.15, discount=0.6, epsilon=0.3)
        self.assertEqual(len(scores), 120)
        learned = rollout(env, policy.__getitem__)
        hold = rollout(env, lambda _: 2)
        self.assertGreater(learned["net_return"], 0.95 * hold["net_return"])
