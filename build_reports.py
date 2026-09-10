#!/usr/bin/env python3
"""Build the two report files from data/donations.json.

Outputs:
  data/names_unique.csv   unique donor names + donation count + total amount
  data/lithuanian.csv     likely Lithuanian donors (tiers T1-T5, with evidence)
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import lithuanian as lt

DATA = Path(__file__).parent / "data"


def _amount(a):
    if a is None:
        return 0.0
    try:
        return float(a)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    rows = json.loads((DATA / "donations.json").read_text())["donations"]

    agg = defaultdict(lambda: {"count": 0, "total": 0.0})
    for r in rows:
        a = agg[r["name"]]
        a["count"] += 1
        a["total"] += _amount(r.get("amount"))

    with (DATA / "names_unique.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name", "donation_count", "total_amount"])
        for n, a in sorted(agg.items(), key=lambda kv: kv[0].lower()):
            w.writerow([n, a["count"], round(a["total"], 2)])

    tiers = {"T1": [], "T2": [], "T3": [], "T4": [], "T5": []}
    for n, a in agg.items():
        tier, ev = lt.classify(n)
        if tier in tiers:
            tiers[tier].append((n, a, ev))

    with (DATA / "lithuanian.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["tier", "name", "total_amount", "donation_count", "evidence"])
        for t in ("T1", "T2", "T3", "T4", "T5"):
            for n, a, ev in sorted(tiers[t], key=lambda x: (-x[1]["total"], x[0].lower())):
                w.writerow([t, n, round(a["total"], 2), a["count"], ev])

    n_lith = sum(len(v) for v in tiers.values())
    print(f"wrote names_unique.csv ({len(agg)} names) and "
          f"lithuanian.csv ({n_lith} candidates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())