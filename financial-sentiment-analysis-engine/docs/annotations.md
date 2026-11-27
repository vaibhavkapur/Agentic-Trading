# Annotation protocol · desk-notes.v1

The annotation unit is one canonical article and one uniquely linked issuer. Annotate the described change for that issuer from the headline and body together. The labels describe business news in context. Price outcomes are unused.

- **Positive** covers an explicitly favorable development such as an order win, improved margins or a raised forecast. Use rule `favorable-realized-or-guided`.
- **Negative** covers an explicitly adverse development such as a contract loss, a miss or a cut. Use `adverse-realized-or-guided`.
- **Neutral** covers a factual announcement without a directional change, including meeting logistics and an unchanged schedule. Use `factual-no-direction`.
- **Uncertain** covers unverified claims, an unresolved direction, recognizable sarcasm or conflicting directional evidence. Use `insufficient-or-conflicting-evidence`.

In multi-company stories label each attributable issuer independently. Exclude unresolved aliases from issuer labels. Skip syndicated copies. For a joint or inseparable claim, abstain where issuer-level attribution is uncertain. A neutral observation supplies evidence to an aggregate. An abstention contributes to its article and abstained counts only.

## Provenance and time splits

All 83 input records are original synthetic observations. The fixtures contain 81 canonical articles, one unresolved ambiguous article, and one article with two issuer labels. This yields 81 annotations. The simulated sources are synthetic-desk and synthetic-wire. Annotation instants are simulated one hour after first availability. The corpus has one editorial labeling pass, with no independent adjudication or measured annotator agreement.

Partition canonical articles on first availability. The training interval ends at 2025-03-01 00:00 UTC. Calibration runs from then until 2025-04-01 00:00 UTC. Test runs from then until 2025-06-01 00:00 UTC. All upper bounds are exclusive. Evaluate a label only when it is known by its partition cutoff. Quarantine later labels from that partition. A copy appearing in a later period cannot enter that period as a new observation.

The versioned config sets cutoffs, lexicon, aliases, confidence policy and temperature candidates. The two JSONL files are the reference snapshot. Record a new corpus/config version and regenerate evidence when the fixture design changes.
