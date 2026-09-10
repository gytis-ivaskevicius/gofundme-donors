# GoFundMe Donor Tracker

Automated, append-only archive of non-anonymous donations for a GoFundMe
fundraiser, refreshed nightly via GitHub Actions. Extracts **unique donor
names** and flags **likely Lithuanian donors** using a name classifier.

Campaign (default): `support-for-lindsay-clancys-parents`
(Fundraiser ID `106954089` — The Musgrove Family Fund by Brandee Mulligan)

## How it works

1. **`fetch_donations.py`** — pages through GoFundMe's public GraphQL API
   (`graphql.gofundme.com`, `GetFundraiserDonations`). No auth or cookies
   required. Skips anonymous donations and de-duplicates by donation ID.
   **Incremental by default**: pages from the newest donations backwards and
   stops at the first fully-known page, so a typical night costs 1–3 requests
   instead of hundreds. Pass `--full` to refetch everything.
2. **`build_reports.py`** — generates all `data/` artifacts.
3. **GitHub Actions** — runs nightly (03:17 UTC) + on `workflow_dispatch`
   (tick *full refetch* to re-scan the entire history), commits any data
   changes back to the repo.

## Data (in `data/`)

| File | Contents |
|---|---|
| `names_unique.csv` | unique donor names + donation count + total amount |
| `lithuanian.csv` | Lithuanian candidates with evidence tier |
| `donations.json` | internal state (full record list; needed for incremental updates) |

Classifier inputs live in `corpora/` (Wiktionary + Wikidata name lists).

## Lithuanian classifier

Evidence tiers (`lithuanian.py`), strongest first:

- **T1** — surname in the Wiktionary *Lithuanian surnames* corpus (with
  gender variants; includes `-aitė/-ienė` etc.)
- **T2** — strongly Lithuanian morphology: `-auskas, -avičius, -evičius,
  -iūnas, -aitis, -ytis, -inskas, -ickas, -onis, ...`
- **T3** — feminine suffix (`-aitė/-ytė/-ienė`) + supporting evidence
- **T4** — anglicized spelling (w-for-v, e.g. `Wychunas` for `Vyčiūnas`)
- **T5** — distinctive Lithuanian given name only (verify manually)
- **T6** — *archive only*: surname of any Wikidata person with Lithuanian
  citizenship (includes naturalized citizens / Polish-Lithuanians — not a
  strong signal; not emitted by default)

Caveats: donors with fully anglicized or married surnames are invisible to
any name-based method, and anonymous donations (≈30% here) are skipped.

## Local use

```bash
python3 fetch_donations.py --slug "any-campaign-slug"      # incremental
python3 fetch_donations.py --slug "any-campaign-slug" --full  # full re-scan
python3 build_reports.py
```

## Configuration

- **Change campaign**: set repo variable `GFM_SLUG` (Settings → Secrets and
  variables → Actions → Variables). Rum `workflow_dispatch` to refresh now.

All donor names come from GoFundMe's public campaign page — the data is
already public. No private or anonymous donor information is included.