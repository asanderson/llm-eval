# legal-benchmark results

Status: **complete**. Execution classes: **fixture**. Data class: **public-synthetic**. Cohorts: **4**.

Campaign: `legal-evaluation-windows`. Experiment run: `retrieval-legal-benchmark-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Legal summary](legal-summary.json) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

Fixture runs do not measure a model. Every output requires human review. This bundle is a validated projection: it holds enumerated categories, opaque ids, hashes, versioned numbers, coverage and coarse status, and no document text, prompt, answer, citation, grader comment or path.

## Configuration coverage

| Job | Mode | OS | Execution kind | Status | Attempts | Reason |
|---|---|---|---|---|---:|---|
| `retrieval-legal-benchmark-1-a051474dea68` | retrieval | windows-11-native | fixture | succeeded | 1 | unavailable |

## Cohorts

Each job and arm is one cohort. Two runs are comparable only when their cohort digests are equal. Every score has its count; scores without a denominator are unavailable, and the missing scores are counted.

### Job `retrieval-legal-benchmark-1-a051474dea68`, arm `filters-only`

Cohort `6bf6a5a2277b`. Run status: **complete**.

| Metric | Value | Count | Low | High | Missing |
|---|---:|---:|---:|---:|---:|
| status.ok | 16 | 16 | unavailable | unavailable | 0 |
| status.invalid | 0 | 16 | unavailable | unavailable | 0 |
| status.error | 0 | 16 | unavailable | unavailable | 0 |
| status.missing | 0 | 16 | unavailable | unavailable | 0 |
| retrieval.evidence_recall_at_5 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.authority_recall_at_5 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.evidence_ndcg_at_10 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.authority_ndcg_at_10 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.prompt_evidence_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_authority_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.exact_version_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.ineligible_version_leakage | 0.0 | 16 | unavailable | unavailable | 0 |
| retrieval.adverse_authority_coverage | 1.0 | 1 | unavailable | unavailable | 15 |
| retrieval.retrieved_passages | 8.9375 | 16 | unavailable | unavailable | 0 |
| retrieval.retrieved_tokens | 133.125 | 16 | unavailable | unavailable | 0 |
| elapsed_s.median | 8e-05 | 16 | unavailable | unavailable | 0 |
| elapsed_s.p95 | 0.000408 | 16 | unavailable | unavailable | 0 |
| first_output_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_output_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | unavailable | 0 | unavailable | unavailable | 16 |
| rate.revised | unavailable | 0 | unavailable | unavailable | 16 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |

### Job `retrieval-legal-benchmark-1-a051474dea68`, arm `lexical`

Cohort `cd5c9a086d15`. Run status: **complete**.

| Metric | Value | Count | Low | High | Missing |
|---|---:|---:|---:|---:|---:|
| status.ok | 16 | 16 | unavailable | unavailable | 0 |
| status.invalid | 0 | 16 | unavailable | unavailable | 0 |
| status.error | 0 | 16 | unavailable | unavailable | 0 |
| status.missing | 0 | 16 | unavailable | unavailable | 0 |
| retrieval.evidence_recall_at_5 | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.authority_recall_at_5 | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.evidence_ndcg_at_10 | 0.994266 | 14 | unavailable | unavailable | 2 |
| retrieval.authority_ndcg_at_10 | 0.973638 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_evidence_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_authority_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.exact_version_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.ineligible_version_leakage | 0.075 | 16 | unavailable | unavailable | 0 |
| retrieval.adverse_authority_coverage | 1.0 | 1 | unavailable | unavailable | 15 |
| retrieval.retrieved_passages | 7.1875 | 16 | unavailable | unavailable | 0 |
| retrieval.retrieved_tokens | 107.25 | 16 | unavailable | unavailable | 0 |
| elapsed_s.median | 0.000149 | 16 | unavailable | unavailable | 0 |
| elapsed_s.p95 | 0.000295 | 16 | unavailable | unavailable | 0 |
| first_output_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_output_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | unavailable | 0 | unavailable | unavailable | 16 |
| rate.revised | unavailable | 0 | unavailable | unavailable | 16 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |

### Job `retrieval-legal-benchmark-1-a051474dea68`, arm `lexical-eligible`

Cohort `6f2d41f843f3`. Run status: **complete**.

| Metric | Value | Count | Low | High | Missing |
|---|---:|---:|---:|---:|---:|
| status.ok | 16 | 16 | unavailable | unavailable | 0 |
| status.invalid | 0 | 16 | unavailable | unavailable | 0 |
| status.error | 0 | 16 | unavailable | unavailable | 0 |
| status.missing | 0 | 16 | unavailable | unavailable | 0 |
| retrieval.evidence_recall_at_5 | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.authority_recall_at_5 | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.evidence_ndcg_at_10 | 0.994266 | 14 | unavailable | unavailable | 2 |
| retrieval.authority_ndcg_at_10 | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_evidence_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_authority_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.exact_version_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.ineligible_version_leakage | 0.0 | 16 | unavailable | unavailable | 0 |
| retrieval.adverse_authority_coverage | 1.0 | 1 | unavailable | unavailable | 15 |
| retrieval.retrieved_passages | 6.9375 | 16 | unavailable | unavailable | 0 |
| retrieval.retrieved_tokens | 100.3125 | 16 | unavailable | unavailable | 0 |
| elapsed_s.median | 0.000156 | 16 | unavailable | unavailable | 0 |
| elapsed_s.p95 | 0.000282 | 16 | unavailable | unavailable | 0 |
| first_output_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_output_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | unavailable | 0 | unavailable | unavailable | 16 |
| rate.revised | unavailable | 0 | unavailable | unavailable | 16 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |

### Job `retrieval-legal-benchmark-1-a051474dea68`, arm `no-context`

Cohort `baeeaeeac14f`. Run status: **complete**.

| Metric | Value | Count | Low | High | Missing |
|---|---:|---:|---:|---:|---:|
| status.ok | 16 | 16 | unavailable | unavailable | 0 |
| status.invalid | 0 | 16 | unavailable | unavailable | 0 |
| status.error | 0 | 16 | unavailable | unavailable | 0 |
| status.missing | 0 | 16 | unavailable | unavailable | 0 |
| retrieval.evidence_recall_at_5 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.authority_recall_at_5 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.evidence_ndcg_at_10 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.authority_ndcg_at_10 | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.prompt_evidence_recall | 1.0 | 14 | unavailable | unavailable | 2 |
| retrieval.prompt_authority_recall | 0.0 | 14 | unavailable | unavailable | 2 |
| retrieval.exact_version_recall | 0.0 | 14 | unavailable | unavailable | 2 |
| retrieval.ineligible_version_leakage | unavailable | 0 | unavailable | unavailable | 16 |
| retrieval.adverse_authority_coverage | 0.0 | 1 | unavailable | unavailable | 15 |
| retrieval.retrieved_passages | 2.1875 | 16 | unavailable | unavailable | 0 |
| retrieval.retrieved_tokens | 22.25 | 16 | unavailable | unavailable | 0 |
| elapsed_s.median | 4.2e-05 | 16 | unavailable | unavailable | 0 |
| elapsed_s.p95 | 0.000105 | 16 | unavailable | unavailable | 0 |
| first_output_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_output_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| first_visible_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | unavailable | 0 | unavailable | unavailable | 16 |
| rate.revised | unavailable | 0 | unavailable | unavailable | 16 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |

## Paired differences

No job of this run compares arms.

## Interpretation

Intervals are bootstrap percentiles over matter families and are unavailable below six families. The legal summary grades every arm, the reference arm included; the generic summary excludes the reference arm, whose rows publish no number. For a retrieval job the generic quality pass rate is the exact-version pass rate and its cohort has no pass rate of its own. Per-matter rows are published for the fixture smoke mode only; the retrieval, generation, workflow and score modes publish cohort aggregates.
