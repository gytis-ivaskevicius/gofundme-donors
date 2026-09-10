#!/usr/bin/env python3
"""Fetch non-anonymous donations for a GoFundMe fundraiser via their GraphQL API.

Incremental by default: pages from the NEWEST donations backwards (`last: 50`,
`before: endCursor`) and stops as soon as an entire page is already known.
New donations arrive with ever-increasing IDs, so donations older than the
first fully-known page are guaranteed to be known already. A quiet night costs
1 request; a busy one costs a handful. Pass `--full` to refetch everything.

The public endpoint works without authentication or cookies.

Usage: python3 fetch_donations.py [--slug SLUG] [--out data] [--full]
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://graphql.gofundme.com/graphql"
PAGE_SIZE = 50  # API caps page size at 50

QUERY = """
query GetFundraiserDonations($slug: ID!, $first: Int, $last: Int, $before: String, $after: String) {
  fundraiser(slug: $slug) {
    id
    donations(first: $first, last: $last, before: $before, after: $after) {
      totalCount
      edges {
        node {
          id
          name
          isAnonymous
          amount { amount currencyCode __typename }
          createdAt
          isOffline
          isRecurring
          isVerified
          __typename
        }
        __typename
      }
      pageInfo { endCursor hasNextPage hasPreviousPage __typename }
      __typename
    }
    __typename
  }
}
"""

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "client-name": "SSR Frontend Client",
    "client-version": "1.0.0",
    "origin": "https://www.gofundme.com",
    "referer": "https://www.gofundme.com/",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
}


def fetch_page(slug: str, before: str | None = None) -> dict:
    variables = {"slug": slug, "last": PAGE_SIZE}
    if before:
        variables["before"] = before
    body = json.dumps(
        {"operationName": "GetFundraiserDonations", "variables": variables, "query": QUERY}
    ).encode()
    last_err = None
    for attempt in range(7):
        try:
            req = urllib.request.Request(API, data=body, method="POST", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001 - network/HTTP errors, retry all
            last_err = e
            wait = 3 * (attempt + 1)
            print(f"  page fetch error {e!r}, retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"gave up fetching page before={before}: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="support-for-lindsay-clancys-parents")
    ap.add_argument("--out", default="data")
    ap.add_argument("--full", action="store_true", help="refetch entire history")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "donations.json"

    existing = []
    known: set[str] = set()
    if path.exists():
        existing = json.loads(path.read_text())["donations"]
        if not args.full:
            known = {r["id"] for r in existing}
    elif not args.full:
        # no snapshot yet -> full history in one pass anyway
        args.full = True

    mode = "full" if args.full else "incremental"
    print(f"fetch mode: {mode} (known donations: {len(known)})", file=sys.stderr)

    new_rows = []
    anon_new = 0
    total_count = None
    fundraiser_id = None
    before = None
    page = 0

    while True:
        page += 1
        data = fetch_page(args.slug, before)
        fdr = (data.get("data") or {}).get("fundraiser")
        if not fdr:
            print("unexpected response:", json.dumps(data)[:400], file=sys.stderr)
            return 1
        conn = fdr.get("donations") or {}
        if fundraiser_id is None:
            fundraiser_id = fdr.get("id")
        if total_count is None:
            total_count = conn.get("totalCount")
        edges = conn.get("edges") or []
        if not edges:
            break

        page_new = 0
        page_known = 0
        page_anon = 0
        for e in edges:
            node = e["node"]
            nid = node.get("id")
            if node.get("isAnonymous"):
                anon_new += 1
                page_anon += 1
                continue
            if args.full:
                if nid in known:  # de-dup guard for full mode
                    continue
                known.add(nid)
                new_rows.append(_record(node))
            else:
                if nid in known:
                    page_known += 1
                else:
                    known.add(nid)
                    page_new += 1
                    new_rows.append(_record(node))

        if page % 5 == 0 or page_new:
            print(
                f"  page {page}: {len(edges)} seen "
                f"({page_new} new, {page_known} known, {page_anon} anon)",
                file=sys.stderr,
            )
        if args.full:
            if not conn.get("pageInfo", {}).get("hasNextPage"):
                break
        elif page_new == 0 and page_known > 0:
            # all non-anonymous donations on this page already known;
            # older pages only contain older IDs that are known too
            print("  all remaining pages known; stopping", file=sys.stderr)
            break
        nxt = (conn.get("pageInfo") or {}).get("endCursor")
        if not nxt or nxt == before:
            print("cursor did not advance; stopping", file=sys.stderr)
            break
        before = nxt
        time.sleep(0.4)

    merged = {r["id"]: _slim(r) for r in existing}
    for r in new_rows:
        merged[r["id"]] = r
    donations = [merged[i] for i in sorted(merged, key=lambda x: int(x))]

    anon_estimate = max(0, (total_count or 0) - len(donations))

    payload = {
        "fundraiser_slug": args.slug,
        "fundraiser_id": fundraiser_id,
        "total_count": total_count,
        "anonymous_skipped": anon_new if args.full else anon_estimate,
        "non_anonymous": len(donations),
        "new_this_run": len(new_rows),
        "mode": mode,
        "donations": donations,
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    (out_dir / ".last_run.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_this_run": len(new_rows),
        "total_count": total_count,
    }, indent=1))
    print(
        f"DONE: {len(new_rows)} new donations; total stored {len(donations)} "
        f"of {total_count} (mode={mode}) -> {path}",
        file=sys.stderr,
    )
    return 0


def _record(node: dict) -> dict:
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "amount": (node.get("amount") or {}).get("amount"),
        "currency": (node.get("amount") or {}).get("currencyCode"),
        "createdAt": node.get("createdAt"),
    }


def _slim(r: dict) -> dict:
    """Normalize an existing stored record to the slim schema."""
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "amount": r.get("amount"),
        "currency": r.get("currency"),
        "createdAt": r.get("createdAt"),
    }


if __name__ == "__main__":
    sys.exit(main())