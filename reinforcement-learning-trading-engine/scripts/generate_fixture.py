"""Generate the bundled original synthetic session series, using only the stdlib."""
import csv
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / "data/fixtures"


def main():
    seed = 7025
    rng = random.Random(seed)
    path = DIRECTORY / "sessions.csv"
    day = date(2023, 1, 2)
    close = 100
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("opened", "closed", "available", "open_usd", "close_usd", "auction_shares"))
        for i in range(361):
            while day.weekday() >= 5:
                day += timedelta(days=1)
            drift = (0.0015, -0.002, 0.0002)[(i // 40) % 3]
            opening = close * math.exp(rng.uniform(-0.006, 0.006))
            close = opening * math.exp(drift + rng.uniform(-0.016, 0.016))
            at_close = f"{day}T21:00:00Z"
            writer.writerow((f"{day}T14:30:00Z", at_close, at_close,
                             f"{opening:.6f}", f"{close:.6f}", rng.randint(3000, 30000)))
            day += timedelta(days=1)
    manifest = dict(schema="synthetic-sessions/v1", asset="SIM-USD", currency="USD",
                    provenance="generated", generator="scripts/generate_fixture.py", seed=seed,
                    sessions=361, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    entitlement="Original generated fixture for local simulation and tests.")
    (DIRECTORY / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
