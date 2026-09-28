"""Build the toy pack's corpus: 50 invented works about an invented field.

The conformance test needs a corpus small enough to run an engine
against in minutes, and one no engine can have seen before: every work
here is fiction (a luminescent cave moss, Lumobrya lucens, that does not
exist), and every work id sits in a block OpenAlex has not issued
(W9990000001-W9990000050). An engine that cites anything else, or states
a "fact" about Lumobrya the corpus does not contain, brought it in from
outside.

Writes, next to this file (or into --out):
    knowledgebase.sqlite   works, works_fts, statements (hub schema)
    fieldmap.sqlite        citation_edges
    seeds/T1.json, T2.json the two toy questions
    candidates.json        three judge items, one deliberately miscited

    python conformance/toy_pack/build.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ID0 = 9990000000

# (topic, [(year, title, finding)]); five works per topic, ten topics.
# Findings are specific and numeric so a grounded claim can be checked.
TOPICS: list[tuple[str, list[tuple[int, str, str]]]] = [
    ("emission spectrum", [
        (1994, "The green glow of Lumobrya lucens: a first spectrum",
         "Emission peaks at 512 nm with a full width at half maximum of 38 nm."),
        (2001, "A red shoulder in Lumobrya emission",
         "A secondary shoulder at 590 nm carries 11% of the photon flux in mature fronds."),
        (2008, "Spectral shift of Lumobrya emission under desiccation",
         "Desiccated fronds shift the peak from 512 nm to 519 nm within six hours."),
        (2015, "Is the 590 nm shoulder a separate emitter?",
         "The 590 nm shoulder persists in lumA knockouts, suggesting a second emitter."),
        (2022, "Calibrated absolute spectra of Lumobrya fronds",
         "Absolute spectral radiance at 512 nm is 4.1e6 photons per second per square centimetre per nanometre."),
    ]),
    ("enzyme kinetics", [
        (1997, "Lumobrin oxidase: purification and kinetics",
         "Purified lumobrin oxidase has a Km for lumobrin of 42 micromolar."),
        (2003, "Oxygen dependence of lumobrin oxidase",
         "Light output falls to 20% of maximum below 2% oxygen."),
        (2009, "Quantum yield of the lumobrin reaction",
         "The in vitro quantum yield of the lumobrin reaction is 0.07."),
        (2016, "A thermolabile isoform of lumobrin oxidase",
         "Isoform B loses half its activity after ten minutes at 35 C."),
        (2021, "Structure of lumobrin oxidase at 2.1 angstrom",
         "The active site binds lumobrin through a histidine triad."),
    ]),
    ("circadian rhythm", [
        (1999, "Nightly rhythm of Lumobrya glow in constant darkness",
         "Glow oscillates with a 23.6 hour period for at least nine days in constant darkness."),
        (2005, "Light pulses reset the Lumobrya glow rhythm",
         "A 15 minute white light pulse at subjective midnight delays the rhythm by 3.2 hours."),
        (2011, "Rhythm amplitude declines with frond age",
         "Rhythm amplitude in fronds older than 60 days is 40% of that in young fronds."),
        (2018, "Clock gene lumC controls glow timing",
         "lumC mutants glow arrhythmically at a constant intermediate level."),
        (2023, "Is the glow rhythm driven by enzyme supply or oxygen?",
         "Lumobrin oxidase protein levels peak two hours before glow maxima."),
    ]),
    ("humidity", [
        (1996, "Humidity and glow in cave populations of Lumobrya",
         "Glow intensity rises threefold between 70% and 95% relative humidity."),
        (2004, "Rehydration triggers a glow burst",
         "Rewetting dry fronds produces a burst peaking at eight times baseline within 90 seconds."),
        (2010, "Water films and photon escape from fronds",
         "A surface water film reduces measured glow by 25% through scattering."),
        (2017, "Humidity cycling and long-term glow output",
         "Daily humidity cycling lowers mean glow by 30% over four weeks."),
        (2024, "Separating humidity from oxygen effects on glow",
         "At constant oxygen, humidity alone explains 60% of glow variance."),
    ]),
    ("temperature", [
        (1995, "Temperature optimum of Lumobrya glow",
         "Glow is maximal at 14 C and falls to half at 24 C."),
        (2002, "Cold acclimation raises glow output",
         "Fronds acclimated to 6 C for two weeks glow 1.8 times brighter at 14 C."),
        (2007, "Heat shock abolishes glow reversibly",
         "Glow stops within five minutes at 38 C and recovers over 48 hours."),
        (2013, "Arrhenius analysis of glow in intact fronds",
         "Apparent activation energy of glow between 4 C and 14 C is 48 kJ per mol."),
        (2020, "Temperature compensation of the glow rhythm",
         "The rhythm period changes by less than 0.3 hours between 8 C and 20 C."),
    ]),
    ("measurement", [
        (1998, "Photodiode versus photon counting for Lumobrya glow",
         "A photon-counting photomultiplier detects glow at one fiftieth the level a photodiode needs."),
        (2006, "Inter-laboratory disagreement on Lumobrya glow intensity",
         "Three laboratories measuring the same batch reported intensities differing tenfold."),
        (2012, "Dark counts and cooling in glow photometry",
         "Cooling the photomultiplier to -20 C cuts dark counts from 180 to 9 per second."),
        (2019, "A reference light source for moss photometry",
         "A tritium reference source reduced between-laboratory spread from tenfold to 1.4-fold."),
        (2025, "Geometry errors in frond glow measurement",
         "Frond-to-detector distance errors of 2 mm change measured flux by 22%."),
    ]),
    ("ecology", [
        (2000, "Fungus gnats are attracted to Lumobrya glow",
         "Glowing patches caught 4.5 times more fungus gnats than shaded patches."),
        (2006, "Spore dispersal by glow-attracted insects",
         "Gnats visiting glowing fronds carried Lumobrya spores in 38% of cases."),
        (2012, "Glow-free mutants in the field",
         "lumA knockout patches set 55% fewer spores over one season."),
        (2018, "Predators of glow-attracted gnats",
         "Cave spiders web preferentially within 10 cm of glowing patches."),
        (2024, "Does glow pay for itself?",
         "Glow consumes an estimated 3% of frond carbon budget."),
    ]),
    ("genetics", [
        (2002, "Cloning of lumA, the lumobrin oxidase gene",
         "lumA encodes a 41 kDa oxidase expressed only in frond tips."),
        (2008, "lumA knockout abolishes green glow",
         "lumA knockouts emit no detectable 512 nm light."),
        (2014, "lumB supplies lumobrin",
         "lumB knockouts glow only when fed exogenous lumobrin."),
        (2019, "Regulation of lumA by humidity",
         "lumA transcript rises fourfold within one hour of rehydration."),
        (2023, "A lumA paralog in non-glowing relatives",
         "Non-glowing Lumobrya relatives carry a lumA paralog with a disrupted active site."),
    ]),
    ("function controversy", [
        (2003, "Glow as a metabolic byproduct of Lumobrya",
         "Glow correlates with respiration rate (r = 0.81), consistent with a byproduct."),
        (2009, "Glow as a signal: evidence from insect choice",
         "Gnats prefer 512 nm light over 590 nm light in choice arenas by 3 to 1."),
        (2015, "Byproduct or signal? A critical review",
         "No study has manipulated glow while holding respiration constant."),
        (2021, "Decoupling glow from respiration with lumB mutants",
         "lumB mutants respire normally but glow only when fed lumobrin."),
        (2025, "Open problems in Lumobrya luminescence",
         "Whether glow is selected for or merely tolerated remains unresolved."),
    ]),
    ("field survey", [
        (1993, "Distribution of Lumobrya in limestone caves",
         "Lumobrya occurs in 23 of 40 surveyed caves, all above 80% humidity."),
        (2004, "Seasonal glow in cave populations",
         "Cave populations glow twice as bright in the wet season."),
        (2011, "Glow as a population census tool",
         "Glow photographs estimate frond density within 15% of hand counts."),
        (2017, "Decline of Lumobrya in visited caves",
         "Caves with tourist lighting lost 60% of Lumobrya cover in ten years."),
        (2022, "Remote glow monitoring with low-light cameras",
         "A cooled camera detects glowing patches down to 2 square centimetres at 5 m."),
    ]),
]

# mined statements for a few works: (work index, kind, sentence)
STATEMENTS = [
    (25, "limitation", "Our photodiode could not resolve glow below 1e7 photons per second."),
    (26, "controversy", "The tenfold disagreement between laboratories remains unexplained."),
    (27, "measurement_gap", "No laboratory reports its detector's absolute quantum efficiency."),
    (42, "open_question", "Whether glow is selected for remains an open question."),
    (43, "future_work", "Future work should manipulate glow while holding respiration fixed."),
    (44, "open_question", "Why glow and respiration covary is still not understood."),
]

QUESTIONS = {
    "T1": {"title": "Signal or byproduct: is Lumobrya glow selected for?",
           "queries": ["glow signal byproduct", "gnats attracted glow",
                       "glow respiration"],
           "settle": "an experiment that changes glow while holding "
                     "respiration fixed and measures spore dispersal"},
    "T2": {"title": "Why do laboratories disagree tenfold on glow intensity?",
           "queries": ["laboratory disagreement intensity",
                       "reference light source", "dark counts cooling"],
           "settle": "a shared reference source and a stated detector "
                     "efficiency in every report"},
}


def works() -> list[dict]:
    out, n = [], 0
    for topic, items in TOPICS:
        for year, title, finding in items:
            n += 1
            wid = f"W{ID0 + n}"
            abstract = (f"We studied the {topic} of the cave moss Lumobrya "
                        f"lucens. {finding} We discuss what this implies "
                        f"for the {topic} of luminescent mosses.")
            body = (f"{abstract} Methods: fronds were collected from "
                    f"limestone caves and kept at 14 C and 90% relative "
                    f"humidity. Results: {finding}")
            out.append({"work_id": wid, "title": title, "year": year,
                        "abstract": abstract, "body": body,
                        "topic": topic})
    # each work cites the earlier works on its topic and one work before it
    for i, w in enumerate(out):
        same = [v["work_id"] for v in out[:i] if v["topic"] == w["topic"]]
        w["cites"] = same + ([out[i - 1]["work_id"]] if i else [])
    return out


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ws = works()

    kb_path = out_dir / "knowledgebase.sqlite"
    kb_path.unlink(missing_ok=True)
    kb = sqlite3.connect(kb_path)
    kb.executescript("""
        CREATE TABLE works (work_id TEXT, doi TEXT, title TEXT, year REAL,
            type TEXT, cited_by_count INTEGER, core_topic INTEGER,
            is_oa INTEGER, abstract TEXT, has_fulltext INTEGER);
        CREATE VIRTUAL TABLE works_fts USING fts5(
            work_id UNINDEXED, title, abstract, body,
            tokenize='porter unicode61');
        CREATE TABLE statements (work_id TEXT, file TEXT, page INTEGER,
            kind TEXT, sentence TEXT);
    """)
    cited_by = {w["work_id"]: 0 for w in ws}
    for w in ws:
        for c in w["cites"]:
            cited_by[c] += 1
    for w in ws:
        kb.execute("INSERT INTO works VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (w["work_id"], None, w["title"], w["year"], "article",
                    cited_by[w["work_id"]], 1, 1, w["abstract"], 1))
        kb.execute("INSERT INTO works_fts VALUES (?,?,?,?)",
                   (w["work_id"], w["title"], w["abstract"], w["body"]))
    for i, kind, sentence in STATEMENTS:
        kb.execute("INSERT INTO statements VALUES (?,?,?,?,?)",
                   (ws[i]["work_id"], "toy.pdf", 3, kind, sentence))
    kb.commit()

    fm_path = out_dir / "fieldmap.sqlite"
    fm_path.unlink(missing_ok=True)
    fm = sqlite3.connect(fm_path)
    fm.execute("CREATE TABLE citation_edges (src_work_id TEXT, "
               "dst_work_id TEXT)")
    fm.executemany("INSERT INTO citation_edges VALUES (?,?)",
                   [(w["work_id"], c) for w in ws for c in w["cites"]])
    fm.commit()

    seeds = out_dir / "seeds"
    seeds.mkdir(exist_ok=True)
    for qid, q in QUESTIONS.items():
        entry = []
        for query in q["queries"]:
            match = " AND ".join(f'"{t}"' for t in query.split())
            for (wid,) in kb.execute(
                    "SELECT work_id FROM works_fts WHERE works_fts MATCH ? "
                    "ORDER BY bm25(works_fts) LIMIT 3", (match,)):
                w = next(x for x in ws if x["work_id"] == wid)
                if all(e["work_id"] != wid for e in entry):
                    entry.append({"work_id": wid, "title": w["title"],
                                  "year": w["year"], "type": "article",
                                  "text": w["abstract"]})
        seed = {"seed_id": qid, "title": q["title"],
                "quotes": [{"quote": s, "source": f"toy `{ws[i]['work_id']}`"}
                           for i, k, s in STATEMENTS
                           if k in ("open_question", "controversy")
                           and (qid == "T1") == (i >= 40)],
                "what_would_settle_it": q["settle"],
                "claims_mentioned": [], "entry_queries": q["queries"],
                "entry_points": entry, "registry_claims_at_stake": [],
                "registry_all_claim_statements": [],
                "instructions_to_engine": ""}
        (seeds / f"{qid}.json").write_text(
            json.dumps(seed, indent=1), encoding="utf-8")
    kb.close()
    fm.close()

    # judge items: C1 grounded, C2 cites a work that says something else,
    # C3 grounded but its experiment cannot discriminate
    def cited(*idx: int) -> list[dict]:
        return [{"work_id": ws[i]["work_id"], "title": ws[i]["title"],
                 "year": ws[i]["year"], "type": "article",
                 "abstract": ws[i]["abstract"]} for i in idx]

    def item(cid, seed, statement, steps, idx, experiment):
        return {"candidate_id": cid, "seed_id": seed, "statement": statement,
                "scope": {"population": "Lumobrya lucens fronds",
                          "condition": "cave conditions, 14 C, 90% RH",
                          "comparator": "lumB mutants fed lumobrin",
                          "outcome": "spore dispersal by fungus gnats"},
                "null_hypothesis": "no difference in spore dispersal",
                "estimand": "ratio of spores dispersed, glowing vs dark",
                "proposed_experiment": experiment,
                "rationale": [{"step": s, "justification_type": "citation",
                               "work_ids": [ws[i]["work_id"]]}
                              for s, i in steps],
                "cited_works": cited(*idx)}
    candidates = [
        item("C1", "T1",
             "Unfed lumB mutant patches, which respire normally but do not "
             "glow, disperse fewer spores than lumobrin-fed lumB patches.",
             [("lumB mutants respire normally and glow only when fed "
               "lumobrin.", 43),
              ("Gnats visiting glowing fronds carry spores in 38% of "
               "cases.", 31)], (43, 31),
             "Paired cave plots of fed and unfed lumB mutants; count "
             "spores on trapped gnats over one season."),
        item("C2", "T1",
             "Glow is a byproduct because lumobrin oxidase is most active "
             "at 35 C, far above cave temperature.",
             [("Lumobrin oxidase is most active at 35 C.", 8)], (8,),
             "Measure glow of fronds at 14 C and 35 C."),
        item("C3", "T2",
             "Laboratories disagree on glow intensity because of detector "
             "geometry rather than detector type.",
             [("Distance errors of 2 mm change measured flux by 22%.", 29),
              ("Three laboratories disagreed tenfold on one batch.", 26)],
             (29, 26),
             "Ask laboratories whether they think geometry matters."),
    ]
    (out_dir / "candidates.json").write_text(
        json.dumps(candidates, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE)
    build(ap.parse_args().out)


if __name__ == "__main__":
    main()
