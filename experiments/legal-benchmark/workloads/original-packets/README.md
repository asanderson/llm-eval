# original-packets

A small packet suite built by `llm_eval.experiments.legal_benchmark.ingest` from raw files under `raw/`. Everything is original and fictional: the jurisdiction is the invented "Commonwealth of Veld" of `original-smoke`, but every statute, fact, name and address here is new, and email addresses use the reserved `.example` domain.

Lock: `benchmark_id: legal-original-packets`, `split_id: calibration`, `data_class: public-synthetic`, `revision: 2026-11-11.1`. The split is disjoint from `original-smoke` (`split_id: smoke`): no family id, authority id, citation or matter question is shared, so a threshold can be calibrated here and checked on the smoke suite. It is a calibration fixture at a reduced count (two families), not the plan's 12 calibration families, and no result on it supports adopting anything.

| Family | Paired change | Recommendations under the fixture rules |
|---|---|---|
| `p1-quay` | Earlier operative date: the older text of the same citation adds a written-warning element; both matters hold a byte-identical patrol report and the same email, each copy dated on the day of its own matter | `p1-quay-a` charge, `p1-quay-b` defer |
| `p2-kiln` | An email attachment (a permit register extract) supplies the missing element | `p2-kiln-a` defer, `p2-kiln-b` charge |

Raw files: patrol, inspection and statement reports (`.txt`), three `.eml` messages (the registry reply with a quoted request, once per family-1 matter and dated on its operative date, and the permit desk message with a `.txt` attachment, sent before the operative date of its matter), one prior brief of `p1-quay-a` that is hidden from both matters of its family, one shared template, one reviewer note (`source_set: review`, written to `review.json`, never to a candidate file) and four authority texts, two of which are versions of `Veld Harbor Ordinance s9.2`. The storm-shelter exemption `vho-9-4` is `weight: persuasive` and is never established. `collection.json` carries a policy with every default switch written out and an availability cutoff on or after every operative date; every authority has a publication snapshot and a `status_as_of`.

## Rebuilding

The raw files and `collection.json`, `visibility.json` and `rubric.json` are authored; the other manifests are generated:

```bash
python -m llm_eval.experiments.legal_benchmark.ingest --collection experiments/legal-benchmark/workloads/original-packets/collection.json \
  --visibility experiments/legal-benchmark/workloads/original-packets/visibility.json --output experiments/legal-benchmark/workloads/original-packets \
  --lock --benchmark-id legal-original-packets --revision 2026-11-11.1 --split-id calibration
```

The prior brief reveals the resolution of family 1. It is a shared candidate source, so the candidate view of every matter contains it; it is kept from the two matters of its own family only by its `excluded_matters`, which retrieval must enforce (a candidate view does not filter it).

Re-ingesting reproduces `matters.json`, `corpus.json`, `review.json` and `ingest-report.json` byte for byte (`tests/test_legal_ingest.py`). Raw files are checked out without line-ending conversion (`.gitattributes`: `-text`), because their SHA-256 is pinned.
