# Diagnostics

Provisional: Medium (4.17/14)

Provisionally addressed: 4 of 7. Provisional points: 4.17 of 14. Unsupported quotes rejected: 2. Replies missing: 0. Sections: 6. Samples: 3.

Intra-section rule: mean of 3 samples. Inter-section rule in force: top2 (existence-asserting criteria always take the max).
Totals under every inter-section rule: top2 4.17   corroborated 4.33   accumulate 4.33   max 5.33

## SUMMARY
grades: motivation 2.00  audience 0.50  prior_art 1.50  vehicle 0.17  coordination 0.00  insufficiency 0.00  implementation 0.00
sample agreement: 39 of 42 section-criterion pairs unanimous (93%)
single-sample totals would have been: 4.00 / 4.50 / 4.00   (all 3 samples: 4.17)
headings: h2 5
on threshold: prior_art
splits: motivation[4] 1/1/0  prior_art[3] 1/0/0  vehicle[2] 0/1/0
## END SUMMARY

## motivation - grade 2.00 (fired in 3 of 6 sections, strong in 2)
under each rule: top2 2.00   corroborated 2.00   accumulate 2.00   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     2/2/2  -> 2.00
  [3] Motivation                                   2/2/2  -> 2.00
  [4] Proposed Naming: std::dynamicformat          1/1/0  -> 0.67
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 3 of 18 passes): As a result, `std::runtime_format` can now be evaluated at compile time, making its name misleading.
candidate 2 (found by 3 of 18 passes): Despite its name, `std::runtime_format` can be evaluated at compile time.
candidate 3 (found by 1 of 18 passes): This reads naturally and avoids semantic contradiction.
candidate 4 (found by 1 of 18 passes): The format string is dynamically provided

## audience - grade 0.50 (fired in 1 of 6 sections, strong in 0)
under each rule: top2 0.50   corroborated 1.00   accumulate 0.50   max 1.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      1/1/1  -> 1.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 3 of 18 passes): If this is adopted for C++26 there will be no impact on existing code since `std::runtime_format` is a C++26 feature.

## prior_art - grade 1.50 (fired in 3 of 6 sections, strong in 1)  (ON THRESHOLD)
under each rule: top2 1.50   corroborated 1.00   accumulate 1.67   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     2/2/2  -> 2.00
  [3] Motivation                                   1/0/0  -> 0.33
  [4] Proposed Naming: std::dynamicformat          1/1/1  -> 1.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 3 of 18 passes): This aligns with existing terminology `std::format` such as dynamic format specifiers (`check_dynamic_spec`).
candidate 2 (found by 2 of 18 passes): [P2918] introduced `std::runtime_format` to allow opting out of compile-time format string checks in `std::format`. Subsequently, [P3391] made `std::format` usable in constant evaluation. As a result, `std::runtime_format` can now be evaluated at compile time, making its name misleading.
candidate 3 (found by 1 of 18 passes): Subsequently, [P3391] made `std::format` usable in constant evaluation. As a result, `std::runtime_format` can now be evaluated at compile time, making its name misleading.
candidate 4 (found by 1 of 18 passes): The name `std::runtime_format` was accurate when introduced in [P2918], as format strings were not usable in constant evaluation.

## vehicle - grade 0.17 (fired in 1 of 6 sections, strong in 0)
under each rule: top2 0.17   corroborated 0.33   accumulate 0.17   max 0.33
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/1/0  -> 0.33
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): This paper proposes renaming `std::runtime_format` to `std::dynamic_format` to better reflect its semantics and avoid confusion in `constexpr` contexts.

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

## insufficiency - grade 0.00 (fired in 0 of 6 sections, strong in 0)
under each rule: top2 0.00   corroborated 0.00   accumulate 0.00   max 0.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidates: (none validated)

## implementation - grade 0.00  [binary: max] (fired in 0 of 6 sections, strong in 0)
under each rule: top2 0.00   corroborated 0.00   accumulate 0.00   max 0.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidates: (none validated)
