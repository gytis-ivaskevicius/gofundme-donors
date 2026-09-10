#!/usr/bin/env python3
"""Lithuanian donor classifier.

Evidence layers, from strongest to weakest:
  T1  surname present in the Wiktionary "Lithuanian surnames" corpus
      (with auto-generated feminine/masculine gender variants)
  T2  strongly Lithuanian surname morphology (-auskas, -avičius, -iūnas, -aitis, ...)
  T3  generic feminine suffix (-aitė/-ytė/-ienė) backed by a given-name corpus hit
      or Lithuanian diacritics
  T4  anglicized spelling (w-for-v, e.g. Wychunas for Vyčiūnas) + morphology
  T5  distinctive Lithuanian given name only (needs manual verification)
  T6  surname known only from the Wikidata "citizen of Lithuania" set -- includes
      naturalized citizens & Polish-Lithuanian surnames; kept as an archive only,
      NOT treated as a strong match.
"""
import json
import re
import unicodedata
from pathlib import Path

CORPORA = Path(__file__).parent / "corpora"


def _load(name: str) -> list[str]:
    try:
        return json.loads((CORPORA / name).read_text())
    except FileNotFoundError:
        return []


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


_SUR_WIKT = {fold(x) for x in _load("wikt_surnames.json")}
_SUR_WD = {fold(x) for x in _load("wd_family.json")}
_GIVEN = {fold(x) for x in _load("wikt_given.json") + _load("wd_given.json")}

_M2F = {
    "auskas": ["auskiene", "auskaite"], "aitis": ["aite"], "ytis": ["yte"],
    "utis": ["ute"], "iutis": ["iute"], "ius": ["iene", "iute"],
    "us": ["iene", "aite", "ute"], "as": ["iene", "aite"],
    "is": ["iene", "yte"], "ys": ["iene", "yte"],
    "evicius": ["eviciene", "eviciute"], "avicius": ["aviciene", "aviciute"],
    "ovicius": ["oviciene", "oviciute"], "kevicius": ["keviciene", "keviciute"],
    "levicius": ["leviciene", "leviciute"], "inskas": ["inskiene", "inskaite"],
    "ickas": ["ickiene", "ickaite"], "yckas": ["yckiene", "yckaite"],
    "iunas": ["iuniene", "iunaite"], "unas": ["uniene", "unaite"],
    "enas": ["eniene", "enaite"], "onis": ["oniene", "onyte"],
}
_F2M = {
    "auskiene": ["auskas"], "auskaite": ["auskas"], "aite": ["aitis"],
    "yte": ["ytis"], "ute": ["utis"], "iute": ["iutis"],
    "iene": ["ius", "is", "us", "as", "ys"],
    "eviciene": ["evicius"], "eviciute": ["evicius"], "aviciene": ["avicius"],
    "aviciute": ["avicius"], "oviciene": ["ovicius"], "oviciute": ["ovicius"],
    "keviciene": ["kevicius"], "leviciene": ["levicius"],
    "inskiene": ["inskas"], "inskaite": ["inskas"], "ickiene": ["ickas"],
    "ickaite": ["ickas"], "yckiene": ["yckas"], "yckaite": ["yckas"],
    "iuniene": ["iunas"], "iunaite": ["iunas"], "uniene": ["unas"],
    "unaite": ["unas"], "eniene": ["enas"], "enaite": ["enas"],
    "oniene": ["onis"], "onyte": ["onis"],
}


def _variants(base: set[str]) -> set[str]:
    add = set()
    for s in base:
        for m, fems in _M2F.items():
            if s.endswith(m) and len(s) > len(m) + 2:
                st = s[: -len(m)]
                add.update(st + f for f in fems)
        for f, mascs in _F2M.items():
            if s.endswith(f) and len(s) > len(f) + 2:
                st = s[: -len(f)]
                add.update(st + m for m in mascs)
    return add


_WIKT_X = _SUR_WIKT | _variants(_SUR_WIKT)

_STRONG_SUF = [
    "auskyte", "auskiene", "auskaite", "auskas", "aviciene", "aviciute",
    "avicius", "eviciene", "eviciute", "evicius", "oviciene", "oviciute",
    "ovicius", "keviciene", "kevicius", "leviciene", "levicius", "inskiene",
    "inskaite", "inskas", "yckiene", "yckaite", "yckas", "ickiene", "ickaite",
    "ickas", "iuniene", "iunaite", "iunas", "uniene", "unaite", "unas",
    "aitiene", "aityte", "aitis", "ytene", "ytis", "utiene", "utyte", "utis",
    "iute", "iutis", "oniene", "onyte", "onis",
]
_GEN_SUF = ["iene", "aite", "yte", "ute", "enas", "sius"]

_STRONG_DIAC = set("ėųūį")
_GIVEN_DIST = {
    fold(x)
    for x in (
        "mindaugas vytautas gintaras giedrius saulius dainius aurimas zilvinas "
        "kestutis algirdas rimantas raimundas sigitas virginijus zenonas gediminas "
        "justas ignas nojus pijus sarunas rokas vilius deividas eimantas tadas "
        "laurynas matas dominykas jokubas kazys mykolas steponas gytis jomantas "
        "jurate ruta giedre egle ugne migle aiste jurgita rasa zivile birute "
        "neringa milda vaida indre gintare ausra ramune daunoras vaiva mante goda "
        "eivile vilmante domante augustas arijus"
    ).split()
}


def _stem_ok(stem: str) -> str | None:
    """Reject stems that cannot be Lithuanian; allow w-for-v anglicization."""
    if re.search(r"[xq]", stem):
        return "foreign-letter"
    if re.search(r"th|gh|ph|qu", stem):
        return "foreign-digraph"
    if "w" in stem:
        return "w-anglicized"
    return None


def classify(name: str) -> tuple[str | None, str]:
    """Return (tier, evidence). tier None => not flagged as Lithuanian."""
    f = fold(name)
    toks = re.findall(r"[a-z]+", f)
    if not toks:
        return None, ""
    chars = set(name)
    sur = toks[-1]

    if sur in _WIKT_X:
        return "T1", "corpus:wikt"
    if len(toks) >= 2 and toks[-2] in _WIKT_X:
        return "T1", "corpus:wikt(pos2)"

    morph = gen = None
    for suf in _STRONG_SUF:
        if sur.endswith(suf) and len(sur) > len(suf) + 1:
            morph = suf
            break
    if not morph:
        for suf in _GEN_SUF:
            if sur.endswith(suf) and len(sur) > len(suf) + 1:
                gen = suf
                break

    if morph or gen:
        bad = _stem_ok(sur[: -(len(morph or gen))])
        if morph and not bad:
            return "T2", f"morph:{morph}"
        if gen and not bad and (
            any(t in _GIVEN for t in toks)
            or bool(chars & _STRONG_DIAC)
            or sur in _SUR_WD
        ):
            return "T3", f"fem:{gen};support"
        if bad == "w-anglicized":
            return "T4", f"morph:{(morph or gen)};w-for-v"
        return None, ""

    if sur in _SUR_WD:
        return "T6", "corpus:wd(citizen)"
    if any(t in _GIVEN_DIST for t in toks):
        return "T5", f"given:{next(t for t in toks if t in _GIVEN_DIST)}"
    return None, ""


def classify_many(names: list[str]) -> dict[str, tuple[str, str]]:
    return {n: classify(n) for n in names}


if __name__ == "__main__":
    import sys

    for nm in sys.argv[1:]:
        tier, ev = classify(nm)
        print(f"{nm!r:40s} -> {tier or '-':5s} {ev}")