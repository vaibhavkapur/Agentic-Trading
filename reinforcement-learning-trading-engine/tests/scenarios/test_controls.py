import math
import unittest
from dataclasses import replace
from datetime import timedelta

from support import flat, series
from trading_engine.environment import AllocationEnv, MarketRules
from trading_engine.evaluation import rollout, scenarios
from trading_engine.market import ContractError
from trading_engine.policy import train


class ControlScenarios(unittest.TestCase):
    def test_future_price_changes_invisible_before_availability(self):
        original = flat(9)
        altered = original[:6] + tuple(replace(b, open_usd=900, close_usd=990) for b in original[6:])
        a, b = AllocationEnv(original), AllocationEnv(altered)
        self.assertEqual(a.reset(), b.reset())
        for action in (0, 1, 2, 2, 1):
            self.assertEqual(a.step(action), b.step(action))
        self.assertNotEqual(a.step(0), b.step(0))
        with self.assertRaisesRegex(ContractError, "published"):
            AllocationEnv([original[0], replace(original[1], available=original[1].closed + timedelta(hours=1))])

    def test_reward_hacking_churn_loses_costs_and_cannot_farm_terminal_reward(self):
        env = AllocationEnv(flat(11))
        env.reset()
        rewards = [env.step(action)[1] for action in (2, 0) * 5]
        self.assertTrue(all(r < 0 for r in rewards))
        self.assertAlmostEqual(math.exp(sum(rewards)), env.cash / 10000)
        with self.assertRaises(ContractError):
            env.step(0)

    def test_unbounded_actions_fail_before_mutation(self):
        env = AllocationEnv(flat(3))
        _, initial = env.reset()
        for action in (-1, 3, 0.5, True, float("nan"), "2"):
            with self.assertRaises(ContractError) as error:
                env.step(action)
            self.assertEqual(error.exception.code, "action")
            self.assertEqual(env.account(), initial)

    def test_unrealistic_fills_capped_and_zero_liquidity_expires(self):
        env = AllocationEnv(series([(100, 100, 100000), (80, 85, 20), (91, 92, 0)]))
        env.reset()
        *_, fill = env.step(2)
        self.assertEqual(fill["filled_shares"], 1)
        self.assertGreater(fill["fill_price"], 80)
        *_, blocked = env.step(0)
        self.assertEqual(blocked["shares"], 1)
        self.assertIsNone(blocked["fill_price"])
        self.assertEqual(blocked["fee"], 0)

    def test_seed_reproduces_training(self):
        env = AllocationEnv(flat(25))
        def run(seed):
            return train(env, seed, 6, 0.3, 0.9, 0.8)
        self.assertEqual(run(75), run(75))
        self.assertNotEqual(run(75)[1], run(76)[1])

    def test_regime_shift_changes_held_out_drawdown(self):
        base, _, stress = scenarios(flat(20), 4, 19, MarketRules())
        self.assertEqual(base[1][:5], stress[1][:5])
        def hold(scenario):
            return rollout(AllocationEnv(scenario[1], scenario[2], 4, 19), lambda _: 2)
        self.assertGreater(hold(stress)["max_drawdown"], hold(base)["max_drawdown"])
        self.assertLess(hold(stress)["net_return"], hold(base)["net_return"])

    def test_transaction_cost_sensitivity(self):
        def run(rules):
            actions = iter((2, 0) * 4)
            return rollout(AllocationEnv(flat(9), rules), lambda _: next(actions))
        free = run(MarketRules(fee_bps=0, slippage_bps=0))
        costly = run(MarketRules())
        self.assertEqual(free["net_return"], 0)
        self.assertLess(costly["net_return"], 0)
        self.assertAlmostEqual(-costly["net_return"] * 10000, costly["cost_usd"])
