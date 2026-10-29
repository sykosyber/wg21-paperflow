SYNTHETIC: produced by the calibration shim from simulated votes; not a paperweight run, and no finding about paperweight.
# Diagnostics

Provisional: Heavy (9.00/14)

Provisionally addressed: 7 of 7. Provisional points: 9.00 of 14. Unsupported quotes rejected: 0. Replies missing: 0. Sections: 6. Samples: 3.

Intra-section rule: mean of 3 samples. Inter-section rule in force: max (existence-asserting criteria always take the max).
Totals under every inter-section rule: top2 7.67   corroborated 7.67   accumulate 8.33   max 9.00

## SUMMARY
grades: motivation 1.67  audience 0.33  prior_art 2.00  vehicle 1.00  coordination 1.00  insufficiency 1.67  implementation 1.33
sample agreement: 20 of 42 section-criterion pairs unanimous (48%)
single-sample totals would have been: 11.00 / 11.00 / 9.00   (all 3 samples: 9.00)
headings: h2 5
on threshold: motivation, insufficiency
splits: motivation[1] 1/0/0  motivation[2] 0/0/2  motivation[3] 1/0/0  motivation[5] 2/1/2
        audience[1] 1/0/0  audience[4] 0/0/1  prior_art[1] 0/0/1  prior_art[3] 0/1/0
        prior_art[4] 0/0/1  vehicle[2] 1/0/0  vehicle[3] 2/0/1  vehicle[5] 0/2/1
        coordination[1] 0/1/0  coordination[5] 0/2/1  insufficiency[1] 2/2/1
        insufficiency[2] 0/0/1  insufficiency[5] 0/1/1  implementation[1] 2/1/1
        implementation[2] 1/0/1  implementation[3] 0/2/0  implementation[4] 0/1/0
        implementation[5] 0/2/0
## END SUMMARY

## motivation - grade 1.67 (fired in 4 of 6 sections, strong in 1)  (ON THRESHOLD)  (SHARED PASSAGE)
under each rule: top2 1.17   corroborated 1.00   accumulate 1.50   max 1.67
votes by section:
  [1] (front matter: title, abstract and anythi... 1/0/0  -> 0.33
  [2] Abstract                                     0/0/2  -> 0.67
  [3] Motivation                                   1/0/0  -> 0.33
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      2/1/2  -> 1.67
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): - "Victor Zverovich <victor.zverovich@gmail.com>"
candidate 2 (found by 1 of 18 passes): format string checks in `std::format`. Subsequently, [P3391] made
candidate 3 (found by 1 of 18 passes): `std::runtime_format` can be evaluated at compile time. This
candidate 4 (found by 1 of 18 passes): since `std::runtime_format` is a C++26 feature.

## audience - grade 0.33 (fired in 2 of 6 sections, strong in 0)  (SHARED PASSAGE)
under each rule: top2 0.33   corroborated 0.33   accumulate 0.33   max 0.33
votes by section:
  [1] (front matter: title, abstract and anythi... 1/0/0  -> 0.33
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/1  -> 0.33
  [5] Impact on existing code                      0/0/0  -> 0.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): title: "Rename std::runtime_format"
candidate 2 (found by 1 of 18 passes): return std::format(std::runtime_format(fmt), value);

## prior_art - grade 2.00 (fired in 5 of 6 sections, strong in 2)
under each rule: top2 2.00   corroborated 2.00   accumulate 2.00   max 2.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/1  -> 0.33
  [2] Abstract                                     2/2/2  -> 2.00
  [3] Motivation                                   0/1/0  -> 0.33
  [4] Proposed Naming: std::dynamicformat          0/0/1  -> 0.33
  [5] Impact on existing code                      2/2/2  -> 2.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): — Phil Karlton
candidate 2 (found by 1 of 18 passes): at compile time, making its name misleading.
candidate 3 (found by 1 of 18 passes): introduced `std::runtime_format` to allow opting
candidate 4 (found by 1 of 18 passes): semantics and avoid confusion in `constexpr` contexts.

## vehicle - grade 1.00 (fired in 3 of 6 sections, strong in 0)
under each rule: top2 1.00   corroborated 1.00   accumulate 1.17   max 1.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/0/0  -> 0.00
  [2] Abstract                                     1/0/0  -> 0.33
  [3] Motivation                                   2/0/1  -> 1.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/2/1  -> 1.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): can now be evaluated at compile
candidate 2 (found by 1 of 18 passes): actually describes how the format string is obtained.
candidate 3 (found by 1 of 18 passes): with the adoption of `constexpr`
candidate 4 (found by 1 of 18 passes): no impact on existing code since `std::runtime_format` is a

## coordination - grade 1.00 (fired in 2 of 6 sections, strong in 0)  (SHARED PASSAGE)
under each rule: top2 0.67   corroborated 1.00   accumulate 0.67   max 1.00
votes by section:
  [1] (front matter: title, abstract and anythi... 0/1/0  -> 0.33
  [2] Abstract                                     0/0/0  -> 0.00
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/2/1  -> 1.00
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): title: "Rename std::runtime_format"
candidate 2 (found by 1 of 18 passes): will be no impact on existing code since `std::runtime_format` is a C++26
candidate 3 (found by 1 of 18 passes): If this is adopted for C++26 there will

## insufficiency - grade 1.67 (fired in 3 of 6 sections, strong in 1)  (ON THRESHOLD)  (SHARED PASSAGE)
under each rule: top2 1.17   corroborated 1.00   accumulate 1.33   max 1.67
votes by section:
  [1] (front matter: title, abstract and anythi... 2/2/1  -> 1.67
  [2] Abstract                                     0/0/1  -> 0.33
  [3] Motivation                                   0/0/0  -> 0.00
  [4] Proposed Naming: std::dynamicformat          0/0/0  -> 0.00
  [5] Impact on existing code                      0/1/1  -> 0.67
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 2 of 18 passes): title: "Rename std::runtime_format"
candidate 2 (found by 1 of 18 passes): - "Victor Zverovich <victor.zverovich@gmail.com>"
candidate 3 (found by 1 of 18 passes): made `std::format` usable in constant evaluation. As a
candidate 4 (found by 1 of 18 passes): there will be no impact

## implementation - grade 1.33  [binary: max] (fired in 5 of 6 sections, strong in 0)  (SHARED PASSAGE)
under each rule: top2 1.33   corroborated 1.33   accumulate 1.33   max 1.33
votes by section:
  [1] (front matter: title, abstract and anythi... 2/1/1  -> 1.33
  [2] Abstract                                     1/0/1  -> 0.67
  [3] Motivation                                   0/2/0  -> 0.67
  [4] Proposed Naming: std::dynamicformat          0/1/0  -> 0.33
  [5] Impact on existing code                      0/2/0  -> 0.67
  [6] References                                   0/0/0  -> 0.00
candidate 1 (found by 1 of 18 passes): title: "Rename std::runtime_format"
candidate 2 (found by 1 of 18 passes): only two hard things in Computer Science: cache invalidation and naming things.
candidate 3 (found by 1 of 18 passes): - "Victor Zverovich <victor.zverovich@gmail.com>"
candidate 4 (found by 1 of 18 passes): at compile time, making its name
