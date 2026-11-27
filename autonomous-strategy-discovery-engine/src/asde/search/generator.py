"""Deterministic bounded candidate generator within the allowed strategy catalog."""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Set

from asde.dsl.catalog import validate_strategy_spec
from asde.dsl.schema import FamilySpec, Number, StrategyCatalog, StrategySpec
from asde.errors import DslValidationError
from asde.types import sha256_canonical


class BoundedCandidateGenerator:
    """Generates strictly valid, deduplicated StrategySpec candidates inside catalog bounds."""

    def __init__(self, catalog: StrategyCatalog) -> None:
        self.catalog = catalog

    def generate(
        self,
        *,
        families: List[str],
        max_candidates: int,
        seed: int,
    ) -> List[StrategySpec]:
        """Deterministically sample bounded candidates evenly across requested families."""
        if max_candidates <= 0:
            return []
        for f in families:
            if f not in self.catalog.families:
                raise DslValidationError(f"Requested unknown family {f!r} for candidate generation.")

        rng = random.Random(seed)
        specs: List[StrategySpec] = []
        seen_hashes: Set[str] = set()
        attempts = 0
        max_attempts = max(200, max_candidates * 40)

        family_idx = 0
        while len(specs) < max_candidates and attempts < max_attempts:
            attempts += 1
            fam_name = families[family_idx % len(families)]
            family_idx += 1
            fam = self.catalog.families[fam_name]
            params = self._sample_params(fam, rng)
            param_hash = sha256_canonical({"family": fam_name, "parameters": params})[:12]
            if param_hash in seen_hashes:
                continue
            spec = StrategySpec(
                strategy_id=f"{fam_name}_{param_hash}",
                family=fam_name,
                dsl_version=self.catalog.dsl_version,
                parameters=params,
                is_baseline=False,
                description=f"Generated candidate from {fam_name}",
            )
            try:
                validate_strategy_spec(spec, self.catalog)
            except DslValidationError:
                continue
            seen_hashes.add(param_hash)
            specs.append(spec)

        return specs

    def generate_neighbors(
        self,
        base_spec: StrategySpec,
        *,
        max_neighbors: int,
        seed: int,
    ) -> List[StrategySpec]:
        """Generate bounded local perturbations around base_spec for nested inner tuning."""
        if base_spec.is_baseline or base_spec.family not in self.catalog.families:
            return [base_spec]

        fam = self.catalog.families[base_spec.family]
        rng = random.Random(seed)
        neighbors: List[StrategySpec] = [base_spec]
        seen = {sha256_canonical({"family": base_spec.family, "parameters": base_spec.parameters})[:12]}
        param_names = sorted(fam.parameters.keys())
        grids = {p: fam.parameters[p].grid_values() for p in param_names}

        attempts = 0
        max_attempts = max(40, max_neighbors * 20)
        while len(neighbors) < max_neighbors and attempts < max_attempts:
            attempts += 1
            mutated = dict(base_spec.parameters)
            # Perturb 1 or 2 parameters by +-1 grid step
            num_mut = 1 if len(param_names) == 1 else rng.choice([1, 2])
            chosen = rng.sample(param_names, k=min(num_mut, len(param_names)))
            for pname in chosen:
                grid = grids[pname]
                if not grid:
                    continue
                cur = mutated[pname]
                try:
                    idx = min(range(len(grid)), key=lambda i: abs(float(grid[i]) - float(cur)))
                except ValueError:
                    idx = 0
                delta = rng.choice([-1, 1])
                new_idx = max(0, min(len(grid) - 1, idx + delta))
                mutated[pname] = grid[new_idx]

            p_hash = sha256_canonical({"family": base_spec.family, "parameters": mutated})[:12]
            if p_hash in seen:
                continue
            cand = StrategySpec(
                strategy_id=f"{base_spec.family}_{p_hash}",
                family=base_spec.family,
                dsl_version=self.catalog.dsl_version,
                parameters=mutated,
                is_baseline=False,
                max_gross_leverage=base_spec.max_gross_leverage,
                max_single_asset_weight=base_spec.max_single_asset_weight,
                description=f"Inner-tuned neighbor of {base_spec.strategy_id}",
            )
            try:
                validate_strategy_spec(cand, self.catalog)
            except DslValidationError:
                continue
            seen.add(p_hash)
            neighbors.append(cand)

        return neighbors

    @staticmethod
    def _sample_params(fam: FamilySpec, rng: random.Random) -> Dict[str, Number]:
        params: Dict[str, Number] = {}
        for pname in sorted(fam.parameters.keys()):
            grid = fam.parameters[pname].grid_values()
            params[pname] = rng.choice(grid)
        return params
