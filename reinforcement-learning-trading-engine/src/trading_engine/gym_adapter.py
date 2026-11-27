"""Optional native Gymnasium interface."""
import gymnasium as gym
import numpy as np

from .environment import AllocationEnv, STATE_SHAPE, TARGETS


class GymAllocationEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.market = AllocationEnv(*args, **kwargs)
        self.action_space = gym.spaces.Discrete(len(TARGETS))
        self.observation_space = gym.spaces.MultiDiscrete(STATE_SHAPE)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.action_space.seed(seed)
        state, info = self.market.reset(seed=seed, options=options)
        return np.asarray(state), info

    def step(self, action):
        state, reward, terminated, truncated, info = self.market.step(action)
        return np.asarray(state), reward, terminated, truncated, info
