#!/usr/bin/env python3
"""Build report artifacts from data/donations.json.

Outputs (all in data/):
  non_anonymous_donations.json   raw donation records
  non_anonymous_donations.csv    chronological full list
  names_all.txt                  every donor name, chronological
  names_unique.txt               unique name strings, A-Z
  names_unique.csv               unique name + count + total amount
  lithuanian.csv                 Lithuanian candidates (tiers T1-T5)
  lithuanian_archive.csv         T6: Wikidata-citizen surnames (noisy, for review)
  summary.json                   aggregate stats
  SUMMARY.md                     human-readable summary
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import lithuanian as lt

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def fmt_amount(a, cur):
    if a is None:
        return 0.0
    try:
        return float(a)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    payload = json.loads((DATA / "donations.json").read_text())
    rows = payload["donations"]

    # normalize currency to USD-equivalent for totalling (campaign is USD)
    rows = [r for r in rows if (r.get("currency") or "USD") == "USD" or r.get("amount")]

    rows_sorted = sorted(rows, key=lambda r: r.get("createdAt") or "")
    (DATA / "non_anonymous_donations.json").write_text(
        json.dumps(rows_sorted, indent=1, ensure_ascii=False)
    )

    with (DATA / "non_anonymous_donations.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "amount", "currency", "createdAt",
                    "isOffline", "isRecurring", "isVerified"])
        for r in rows_sorted:
            w.writerow([r["id"], r["name"], r["amount"], r["currency"],
                        r["createdAt"], r["isOffline"], r["isRecurring"],
                        r["isVerified"]])

    with (DATA / "names_all.txt").open("w") as f:
        for r in rows_sorted:
            f.write((r["name"] or "") + "\n")

    # unique names (display-name strings) with aggregates
    agg = defaultdict(lambda: {"count": 0, "total": 0.0, "cur": set()})
    for r in rows:
        a = agg[r["name"]]
        a["count"] += 1
        a["total"] += fmt_amount(r["amount"], r.get("currency"))
        a["cur"].add(r.get("currency") or "USD")
    unique = sorted(agg.items(), key=lambda kv: (kv[0].lower()))
    with (DATA / "names_unique.txt").open("w") as f:
        for n, _ in unique:
            f.write(n + "\n")
    with (DATA / "names_unique.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "donation_count", "total_amount", "currencies"])
        for n, a in unique:
            w.writerow([n, a["count"], round(a["total"], 2),
                        "/".join(sorted(a["cur"]))])

    # lithuanian classification
    classified = [(n, *lt.classify(n)) for n, _ in unique]
    tiers = {"T1": [], "T2": [], "T3": [], "T4": [], "T5": [], "T6": []}
    for n, tier, ev in classified:
        if tier:
            tiers[tier].append((n, agg[n]))
    order = ["T1", "T2", "T3", "T4", "T5"]
    with (DATA / "lithuanian.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "name", "total_amount", "donation_count", "evidence"])
        for t in order:
            for n, a in sorted(tiers[t], key=lambda x: (-x[1]["total"], x[0].lower())):
                w.writerow([t, n, round(a["total"], 2), a["count"], ""])
    with (DATA / "lithuanian_archive.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "total_amount", "donation_count"])
        for n, a in sorted(tiers["T6"], key=lambda x: (-x[1]["total"], x[0].lower())):
            w.writerow([n, round(a["total"], 2), a["count"]])

    total_usd = sum(fmt_amount(r["amount"], r.get("currency")) for r in rows)
    lith_main = [n for t in order for n, _ in tiers[t]]
    lith_total = sum(agg[n]["total"] for n in lith_main)
    dates = [r["createdAt"] for r in rows_sorted if r.get("createdAt")]
    top = sorted(agg.items(), key=lambda kv: -kv[1]["total"])[:25]

    summary = {
        "generated_at": payload.get("generated_at"),
        "fundraiser_id": payload.get("fundraiser_id"),
        "total_donations": payload.get("total_count"),
        "anonymous_skipped": payload.get("anonymous_skipped"),
        "non_anonymous": payload.get("non_anonymous"),
        "unique_names": len(unique),
        "date_first": dates[0] if dates else None,
        "date_last": dates[-1] if dates else None,
        "total_amount_usd": round(total_usd, 2),
        "lithuanian_candidates": len(lith_main),
        "lithuanian_total_usd": round(lith_total, 2),
        "lithuanian_by_tier": {t: len(tiers[t]) for t in order},
        "top_donors": [
            {"name": n, "total": round(a["total"], 2), "count": a["count"]}
            for n, a in top
        ],
    }
    (DATA / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False)
    )

    md = [
        "# Donor summary",
        "",
        f"- Total donations: **{summary['total_donations']}** "
        f"(anonymous skipped: {summary['anonymous_skipped']})",
        f"- Non-anonymous: **{summary['non_anonymous']}** in "
        f"{summary['unique_names']} unique names",
        f"- Amount (non-anon): **${summary['total_amount_usd']:,.2f}**",
        f"- Period: {summary['date_first']} → {summary['date_last']}",
        f"- Generated: {summary['generated_at']}",
        "",
        f"## Lithuanian candidates ({len(lith_main)})",
        "",
    ]
    for t in order:
        md.append(f"**{t} — {len(tiers[t])}**")
        md.append("")
        md.append("| name | total | n |")
        md.append("|---|---|---|")
        for n, a in sorted(tiers[t], key=lambda x: (-x[1]["total"], x[0].lower())):
            md.append(f"| {n} | ${a['total']:,.2f} | {a['count']} |")
        md.append("")
    md.append("## Top donors")
    md.append("")
    md.append("| name | total | donations |")
    md.append("|---|---|---|")
    for d in summary["top_donors"]:
        md.append(f"| {d['name']} | ${d['total']:,.2f} | {d['count']} |")
    md.append("")
    (DATA / "SUMMARY.md").write_text("\n".join(md))
    print(f"wrote reports; unique={len(unique)} lithuanian={len(lith_main)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())