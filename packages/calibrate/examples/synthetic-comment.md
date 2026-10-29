SYNTHETIC: this comparison is built from synthetic grades or the Lua shim; its numbers say nothing about paperweight.
### Paperweight calibration · replay · 10 papers × 3 repeats · model shim-calibrated
Gates: 4 of 4 pass

| Metric | Baseline | Candidate | Difference (95% interval) | Reading |
| --- | --- | --- | --- | --- |
| MAE | 0.39 | 1.24 | +0.86 (+0.48 to +1.28) | worse (p < 0.01) |
| Bias | +0.20 | +1.24 | +1.04 (+0.64 to +1.49) | worse (p < 0.01) |
| Correlation | 0.98 | 0.93 | -0.05 (-0.19 to +0.00) | within noise (p 0.36) |

Bands changed: P0533R9 Medium to Heavy (reviewers: Medium); P3556R0 Medium to Heavy (reviewers: Medium); P3953R0 Medium to Heavy (reviewers: Medium); P3978R0 Medium to Heavy (reviewers: Medium)
Stability: sigma 0.15, same band 30 of 30, spans nested 30 of 30
Holdout (2 papers, reported apart): bias +2.00, MAE 2.00, correlation 1.00
Replayed from 2026-10-26-8b903808-shim-calibrated with no model calls.
