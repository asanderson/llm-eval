# legal-benchmark results

Status: **complete**. Execution classes: **model-run**. Data class: **public-synthetic**. Cohorts: **2**.

Campaign: `legal-evaluation-wsl`. Experiment run: `workflow-legal-benchmark-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Legal summary](legal-summary.json) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

Fixture runs do not measure a model. Every output requires human review. This bundle is a validated projection: it holds enumerated categories, opaque ids, hashes, versioned numbers, coverage and coarse status, and no document text, prompt, answer, citation, grader comment or path.

## Configuration coverage

| Job | Mode | OS | Execution kind | Status | Attempts | Reason |
|---|---|---|---|---|---:|---|
| `workflow-legal-benchmark-1-00efc50ea670` | workflow | windows-11-wsl2-ubuntu-26.04 | model-run | succeeded | 1 | unavailable |

## Cohorts

Each job and arm is one cohort. Two runs are comparable only when their cohort digests are equal. Every score has its count; scores without a denominator are unavailable, and the missing scores are counted.

### Job `workflow-legal-benchmark-1-00efc50ea670`, arm `lexical-eligible`

Cohort `6c4923f1df12`. Run status: **complete**.

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
| elapsed_s.median | 39.704026 | 16 | unavailable | unavailable | 0 |
| elapsed_s.p95 | 53.159693 | 16 | unavailable | unavailable | 0 |
| first_output_s.median | 4.09983 | 16 | unavailable | unavailable | 0 |
| first_output_s.p95 | 4.219535 | 16 | unavailable | unavailable | 0 |
| first_visible_s.median | 4.09983 | 16 | unavailable | unavailable | 0 |
| first_visible_s.p95 | 4.219535 | 16 | unavailable | unavailable | 0 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | 0.0 | 16 | unavailable | unavailable | 0 |
| rate.revised | 1.0 | 16 | unavailable | unavailable | 0 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |
| all_pass | 0.0 | 16 | 0.0 | 0.0 | 0 |
| all_pass_deterministic | 0.0 | 16 | unavailable | unavailable | 0 |
| all_pass_reviewed | unavailable | 0 | unavailable | unavailable | 16 |
| criterion.schema_valid | 1.0 | 16 | 1.0 | 1.0 | 0 |
| criterion.recommendation | 0.5625 | 16 | 0.375 | 0.75 | 0 |
| criterion.authority_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.no_ineligible_version_supported | 1.0 | 16 | 1.0 | 1.0 | 0 |
| criterion.element_findings | 0.5 | 16 | 0.1875 | 0.8125 | 0 |
| criterion.conflicts_flagged | 0.9375 | 16 | 0.8125 | 1.0 | 0 |
| criterion.missing_information_flagged | 0.4375 | 16 | 0.1875 | 0.6875 | 0 |
| criterion.adverse_authority | 0.875 | 16 | 0.625 | 1.0 | 0 |
| criterion.untrusted_instruction_flagged | 0.9375 | 16 | 0.8125 | 1.0 | 0 |
| criterion.evidence_grounding | 0.5 | 16 | 0.1875 | 0.8125 | 0 |
| criterion.claim_status | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.citations_resolve | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.pinpoints_correct | 1.0 | 16 | 1.0 | 1.0 | 0 |
| criterion.insufficiency_flagged | 0.625 | 16 | 0.5 | 0.8125 | 0 |
| error.schema_invalid | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.fabricated_citation | 1.0 | 16 | 1.0 | 1.0 | 0 |
| error.unknown_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.pinpoint_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unknown_span | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.ineligible_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unverified_validity | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.out_of_scope_citation | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unsupportive_citation | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unsupported_charge | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.span_digest_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.quote_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.wrong_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.false_charge | 0.4375 | 16 | 0.25 | 0.625 | 0 |
| error.dangerous_commitment | 0.25 | 16 | 0.0625 | 0.4375 | 0 |
| error.absent_element | 0.0 | 16 | 0.0 | 0.0 | 0 |
| author_false_charge | 0.777778 | 9 | unavailable | unavailable | 0 |
| workflow_false_charge | 0.0 | 9 | unavailable | unavailable | 0 |
| author_false_defer | 0.0 | 12 | unavailable | unavailable | 0 |
| workflow_false_defer | 1.0 | 12 | unavailable | unavailable | 0 |
| author_dangerous_commitment | 1.0 | 4 | unavailable | unavailable | 0 |
| workflow_dangerous_commitment | 0.0 | 4 | unavailable | unavailable | 0 |
| abstention | 0.0 | 16 | unavailable | unavailable | 0 |
| forced_defer | 1.0 | 16 | unavailable | unavailable | 0 |
| confusion.charge.charge | 7 | 16 | unavailable | unavailable | 0 |
| confusion.charge.decline | 0 | 16 | unavailable | unavailable | 0 |
| confusion.charge.defer | 0 | 16 | unavailable | unavailable | 0 |
| confusion.charge.none | 0 | 16 | unavailable | unavailable | 0 |
| confusion.decline.charge | 3 | 16 | unavailable | unavailable | 0 |
| confusion.decline.decline | 2 | 16 | unavailable | unavailable | 0 |
| confusion.decline.defer | 0 | 16 | unavailable | unavailable | 0 |
| confusion.decline.none | 0 | 16 | unavailable | unavailable | 0 |
| confusion.defer.charge | 4 | 16 | unavailable | unavailable | 0 |
| confusion.defer.decline | 0 | 16 | unavailable | unavailable | 0 |
| confusion.defer.defer | 0 | 16 | unavailable | unavailable | 0 |
| confusion.defer.none | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.defer | 7 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.defer | 5 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.defer | 4 | 16 | unavailable | unavailable | 0 |
| critical_errors | 1.0 | 16 | unavailable | unavailable | 0 |
| critical_unreviewed | 1.0 | 16 | unavailable | unavailable | 0 |
| missing.pending | 0 | 16 | unavailable | unavailable | 0 |
| missing.unavailable | 0 | 16 | unavailable | unavailable | 0 |
| missing.no_response | 0 | 16 | unavailable | unavailable | 0 |

### Job `workflow-legal-benchmark-1-00efc50ea670`, arm `no-context`

Cohort `472486def2e9`. Run status: **complete**.

| Metric | Value | Count | Low | High | Missing |
|---|---:|---:|---:|---:|---:|
| status.ok | 7 | 16 | unavailable | unavailable | 0 |
| status.invalid | 9 | 16 | unavailable | unavailable | 0 |
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
| elapsed_s.median | 36.637165 | 7 | unavailable | unavailable | 9 |
| elapsed_s.p95 | 55.201834 | 7 | unavailable | unavailable | 9 |
| first_output_s.median | 4.187263 | 7 | unavailable | unavailable | 9 |
| first_output_s.p95 | 5.740694 | 7 | unavailable | unavailable | 9 |
| first_visible_s.median | 4.187263 | 7 | unavailable | unavailable | 9 |
| first_visible_s.p95 | 5.740694 | 7 | unavailable | unavailable | 9 |
| usable_memo_s.median | unavailable | 0 | unavailable | unavailable | 16 |
| usable_memo_s.p95 | unavailable | 0 | unavailable | unavailable | 16 |
| rate.truncated | 0.0 | 16 | unavailable | unavailable | 0 |
| rate.revised | 0.4375 | 16 | unavailable | unavailable | 0 |
| rate.route_fallback | unavailable | 0 | unavailable | unavailable | 16 |
| rate.selector_deferral | unavailable | 0 | unavailable | unavailable | 16 |
| all_pass | 0.0 | 16 | 0.0 | 0.0 | 0 |
| all_pass_deterministic | 0.0 | 16 | unavailable | unavailable | 0 |
| all_pass_reviewed | unavailable | 0 | unavailable | unavailable | 16 |
| criterion.schema_valid | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| criterion.recommendation | 0.25 | 16 | 0.0625 | 0.4375 | 0 |
| criterion.authority_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.no_ineligible_version_supported | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| criterion.element_findings | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.conflicts_flagged | 0.3125 | 16 | 0.0 | 0.625 | 0 |
| criterion.missing_information_flagged | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.adverse_authority | 0.3125 | 16 | 0.0625 | 0.625 | 0 |
| criterion.untrusted_instruction_flagged | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| criterion.evidence_grounding | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.claim_status | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.citations_resolve | 0.0 | 16 | 0.0 | 0.0 | 0 |
| criterion.pinpoints_correct | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| criterion.insufficiency_flagged | 0.25 | 16 | 0.0 | 0.5 | 0 |
| error.schema_invalid | 0.5625 | 16 | 0.25 | 0.875 | 0 |
| error.fabricated_citation | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| error.unknown_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.pinpoint_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unknown_span | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.ineligible_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unverified_validity | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.out_of_scope_citation | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unsupportive_citation | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.unsupported_charge | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.span_digest_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.quote_mismatch | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.wrong_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.false_charge | 0.0625 | 16 | 0.0 | 0.1875 | 0 |
| error.dangerous_commitment | 0.0 | 16 | 0.0 | 0.0 | 0 |
| error.absent_element | 0.4375 | 16 | 0.125 | 0.75 | 0 |
| author_false_charge | 0.111111 | 9 | unavailable | unavailable | 0 |
| workflow_false_charge | 0.0 | 9 | unavailable | unavailable | 0 |
| author_false_defer | 0.166667 | 12 | unavailable | unavailable | 0 |
| workflow_false_defer | 1.0 | 12 | unavailable | unavailable | 0 |
| author_dangerous_commitment | 0.0 | 4 | unavailable | unavailable | 0 |
| workflow_dangerous_commitment | 0.0 | 4 | unavailable | unavailable | 0 |
| abstention | 0.3125 | 16 | unavailable | unavailable | 0 |
| forced_defer | 0.6875 | 16 | unavailable | unavailable | 0 |
| confusion.charge.charge | 1 | 16 | unavailable | unavailable | 0 |
| confusion.charge.decline | 0 | 16 | unavailable | unavailable | 0 |
| confusion.charge.defer | 2 | 16 | unavailable | unavailable | 0 |
| confusion.charge.none | 4 | 16 | unavailable | unavailable | 0 |
| confusion.decline.charge | 1 | 16 | unavailable | unavailable | 0 |
| confusion.decline.decline | 0 | 16 | unavailable | unavailable | 0 |
| confusion.decline.defer | 0 | 16 | unavailable | unavailable | 0 |
| confusion.decline.none | 4 | 16 | unavailable | unavailable | 0 |
| confusion.defer.charge | 0 | 16 | unavailable | unavailable | 0 |
| confusion.defer.decline | 0 | 16 | unavailable | unavailable | 0 |
| confusion.defer.defer | 3 | 16 | unavailable | unavailable | 0 |
| confusion.defer.none | 1 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.charge.defer | 7 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.decline.defer | 5 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.charge | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.decline | 0 | 16 | unavailable | unavailable | 0 |
| workflow_confusion.defer.defer | 4 | 16 | unavailable | unavailable | 0 |
| critical_errors | 1.0 | 16 | unavailable | unavailable | 0 |
| critical_unreviewed | 1.0 | 16 | unavailable | unavailable | 0 |
| missing.pending | 0 | 16 | unavailable | unavailable | 0 |
| missing.unavailable | 0 | 16 | unavailable | unavailable | 0 |
| missing.no_response | 0 | 16 | unavailable | unavailable | 0 |

## Paired differences

| Job | Arm A | Arm B | Metric | Mean (A minus B) | Pairs | Low | High | Missing |
|---|---|---|---|---:|---:|---:|---:|---:|
| `workflow-legal-benchmark-1-00efc50ea670` | no-context | lexical-eligible | all_pass | 0.0 | 16 | 0.0 | 0.0 | 0 |
| `workflow-legal-benchmark-1-00efc50ea670` | no-context | lexical-eligible | error.wrong_version | 0.0 | 16 | 0.0 | 0.0 | 0 |
| `workflow-legal-benchmark-1-00efc50ea670` | no-context | lexical-eligible | error.unsupportive_citation | 0.0 | 16 | 0.0 | 0.0 | 0 |

## Interpretation

Intervals are bootstrap percentiles over matter families and are unavailable below six families. The legal summary grades every arm, the reference arm included; the generic summary excludes the reference arm, whose rows publish no number. For a retrieval job the generic quality pass rate is the exact-version pass rate and its cohort has no pass rate of its own. Per-matter rows are published for the fixture smoke mode only; the retrieval, generation, workflow and score modes publish cohort aggregates.
