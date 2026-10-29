SYNTHETIC: produced by the calibration shim from simulated votes; not a paperweight run, and no finding about paperweight.
# Diagnostics

Provisional: Medium (7.00/14, close to Heavy)

Provisionally addressed: 5 of 7. Provisional points: 7.00 of 14. Unsupported quotes rejected: 0. Replies missing: 0. Sections: 6. Samples: 3.

Intra-section rule: mean of 3 samples. Inter-section rule in force: top2 (existence-asserting criteria always take the max).
Totals under every inter-section rule: top2 7.00   corroborated 7.00   accumulate 7.00   max 8.00

## SUMMARY
grades: motivation 1.00  audience 0.00  prior_art 2.00  vehicle 1.00  coordination 0.00  insufficiency 1.00  implementation 2.00
sample agreement: 42 of 42 section-criterion pairs unanimous (100%)
single-sample totals would have been: 7.00 / 7.00 / 7.00   (all 3 samples: 7.00)
headings: h2 5
on threshold: insufficiency, implementation
splits: none
## END SUMMARY

## motivation - grade 1.00 (fired in 2 of 6 sections, strong in 0)
under each rule: top2 1.00   corroborated 1.00   accumulate 1.00   max 1.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   1/1/1  -> 1.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      1/1/1  -> 1.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): is provided and validated. The term runtime conflates
candidate 2 (found by 1 of 18 passes): as format strings were not
candidate 3 (found by 1 of 18 passes): formatting occurs, but how the format string is provided and validated. The
candidate 4 (found by 1 of 18 passes): be no impact on existing code since `std::runtime_format` is a C++26

## audience - grade 0.00 (fired in 0 of 6 sections, strong in 0)
under each rule: top2 0.00   corroborated 0.00   accumulate 0.00   max 0.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidates: (none validated)

## prior_art - grade 2.00 (fired in 2 of 6 sections, strong in 2)
under each rule: top2 2.00   corroborated 2.00   accumulate 2.00   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     2/2/2  -> 2.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      2/2/2  -> 2.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): `std::runtime_format` to allow opting out of compile-time format string checks
candidate 2 (found by 1 of 18 passes): [P2918] introduced `std::runtime_format` to allow opting out of compile-time
candidate 3 (found by 1 of 18 passes): a result, `std::runtime_format` can now be evaluated at compile time, making
candidate 4 (found by 1 of 18 passes): is adopted for C++26 there will be no impact on existing

## vehicle - grade 1.00 (fired in 2 of 6 sections, strong in 0)
under each rule: top2 1.00   corroborated 1.00   accumulate 1.00   max 1.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     1/1/1  -> 1.00
  [3] Motivation                                   1/1/1  -> 1.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): made `std::format` usable in constant evaluation. As a
candidate 2 (found by 1 of 18 passes): `std::runtime_format` to allow opting out of compile-time format
candidate 3 (found by 1 of 18 passes): its name misleading. This paper proposes renaming `std::runtime_format` to `std::dynamic_format` to
candidate 4 (found by 1 of 18 passes): be evaluated at compile time. This creates a semantic

## coordination - grade 0.00 (fired in 0 of 6 sections, strong in 0)
under each rule: top2 0.00   corroborated 0.00   accumulate 0.00   max 0.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidates: (none validated)

## insufficiency - grade 1.00 (fired in 1 of 6 sections, strong in 1)  (ON THRESHOLD)
under each rule: top2 1.00   corroborated 1.00   accumulate 1.00   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 2/2/2  -> 2.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): There are only two hard things in Computer
candidate 2 (found by 1 of 18 passes): — Phil Karlton
candidate 3 (found by 1 of 18 passes): two hard things in Computer Science: cache invalidation and naming things.

## implementation - grade 2.00  [binary: max] (fired in 1 of 6 sections, strong in 1)  (ON THRESHOLD)
under each rule: top2 2.00   corroborated 2.00   accumulate 2.00   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 2/2/2  -> 2.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 2 of 18 passes): title: "Rename std::runtime_format"
candidate 2 (found by 1 of 18 passes): Science: cache invalidation and naming
