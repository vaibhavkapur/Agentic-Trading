import math
import unittest
from dataclasses import replace

from support import flat, series
from trading_engine.environment import AllocationEnv, MarketRules
from trading_engine.market import ContractError, validate


class AccountingTests(unittest.TestCase):
    def test_fill_cash_mark_and_reward_conserve(self):
        bars = series([(100, 102, 99), (110, 115, 5000), (105, 98, 1000), (101, 103, 5000)])
        env = AllocationEnv(bars)
        _, last = env.reset()
        accumulated = 0
        for i, action in enumerate((1, 2, 0), 1):
            _, reward, done, truncated, info = env.step(action)
            bar = bars[i]
            q = info["filled_shares"]
            self.assertAlmostEqual(info["cash"], last["cash"] - q * info["fill_price"] - info["fee"])
            self.assertAlmostEqual(info["equity"], info["cash"] + info["shares"] * bar.close_usd)
            pnl = last["shares"] * (bar.open_usd - bars[i-1].close_usd)
            pnl += info["shares"] * (bar.close_usd - bar.open_usd)
            self.assertAlmostEqual(info["equity"] - last["equity"], pnl - info["fee"] - info["slippage"])
            self.assertGreaterEqual(info["cash"], 0)
            self.assertGreaterEqual(info["shares"], 0)
            self.assertEqual(done, i == 3)
            self.assertFalse(truncated)
            self.assertEqual(info["decision_time"], last["time"])
            accumulated += reward
            last = info
        self.assertAlmostEqual(math.exp(accumulated), last["equity"] / 10000)
        with self.assertRaises(ContractError):
            env.step(0)

    def test_post_cost_half_target_on_buy_and_sell(self):
        env = AllocationEnv(flat(5))
        env.reset()
        for action in (1, 2, 1, 0):
            *_, info = env.step(action)
            self.assertAlmostEqual(info["shares"] * 100 / info["equity"], action / 2)

    def test_gap_is_earned_only_by_existing_inventory(self):
        env = AllocationEnv(series([(50, 50, 1e5), (100, 100, 1e5), (120, 120, 1e5)]),
                            MarketRules(fee_bps=0, slippage_bps=0))
        env.reset()
        self.assertEqual(env.step(2)[1], 0)
        self.assertAlmostEqual(env.step(0)[1], math.log(1.2))

    def test_invalid_market_contracts(self):
        bars = flat(2)
        for change in (dict(open_usd=0), dict(close_usd=float("nan")), dict(auction_shares=-1),
                       dict(opened=bars[0].closed), dict(available=bars[1].available.replace(tzinfo=None))):
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate([bars[0], replace(bars[1], **change)])
        for change in (dict(fee_bps=-1), dict(participation=1.01), dict(initial_cash=float("inf"))):
            with self.assertRaises(ContractError):
                MarketRules(**change)
