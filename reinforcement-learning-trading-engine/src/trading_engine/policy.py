"""Bounded offline tabular Q-learning and inference-only policy serialization."""
import itertools
import math
import random

from .environment import STATE_SHAPE, TARGETS
from .market import ContractError

STATES = tuple(itertools.product(*(range(n) for n in STATE_SHAPE)))


def greedy(row):
    return max(range(len(TARGETS)), key=row.__getitem__)


def train(env, seed, episodes, alpha, discount, epsilon):
    rng = random.Random(seed)
    table = {state: [0.0] * len(TARGETS) for state in STATES}
    scores = []
    for _ in range(episodes):
        state, _ = env.reset()
        total = 0
        while True:
            row = table[state]
            action = rng.randrange(len(TARGETS)) if rng.random() < epsilon else greedy(row)
            following, reward, done, _, _ = env.step(action)
            target = reward if done else reward + discount * max(table[following])
            row[action] += alpha * (target - row[action])
            total += reward
            if done:
                break
            state = following
        scores.append(math.expm1(total))
    return {state: greedy(row) for state, row in table.items()}, scores


def artifact(policy, provenance):
    return dict(schema="allocation-policy/v1", mode="paper-only", asset="SIM-USD",
                state_schema="momentum-exposure/v1", targets=list(TARGETS),
                actions=[policy[s] for s in STATES], provenance=provenance)


def load_policy(payload):
    if (payload.get("schema"), payload.get("mode"), payload.get("asset"),
        payload.get("state_schema"), payload.get("targets")) != (
            "allocation-policy/v1", "paper-only", "SIM-USD", "momentum-exposure/v1", list(TARGETS)):
        raise ContractError("policy_schema", "Unsupported policy contract")
    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) != len(STATES) or any(
        type(action) is not int or not 0 <= action < len(TARGETS) for action in actions
    ):
        raise ContractError("policy_action", "Invalid policy action table")
    return dict(zip(STATES, actions))
