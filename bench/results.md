# Benchmark results

Current results, rewritten by `bench/run_bench.py` (`bench.ablate` and `bench.calibrate` append their sections for the same run).

## Run 2026-11-11T22:42:57Z

Scored 290 files (229 maintainable). Threshold 9.0. Ground truth: human Overall <= 1.

### Sources and match rate

| project | revision | commit | date | found | missing | LoC exact | LoC within 10% |
|---|---|---|---|---|---|---|---|
| argoUML | month-2020-09 | `6f06c727a1` | 2020-09-27 | 74/74 | 0 | 7 | 36 |
| aoi | spm-bad | `c1aac96fa2` | 2018-12-14 | 70/73 | 3 | 0 | 13 |
| jsweet | 3.0.0-RC4 | `4124c8f732` | 2020-09-08 | 73/73 | 0 | 35 | 48 |
| junit4 | r4.12 | `64155f8a9b` | 2014-12-04 | 73/73 | 0 | 5 | 28 |
| diarymanagement | excluded: not publicly available | | | 0/11 | 11 | | |

LoC agreement compares comment-stripped non-blank lines with the CSV `nos` column (the CSV `line` column is not a line count; `nos` reproduces the paper's LoC baseline).

### Headline

| approach | UC1 acc | UC1 P | UC1 R | UC1 F1 | UC2 P | UC2 R | UC2 F1 | UC2 F0.5 | AUC |
|---|---|---|---|---|---|---|---|---|---|
| codehealth (ours) >= 9 | 0.941 | 0.957 | 0.969 | 0.963 | 0.879 | 0.836 | 0.857 | 0.870 | 0.975 |
| published reference score (Ghost Echoes, Borg et al. 2024) >= 9 | 0.938 | 0.945 | 0.978 | 0.961 | 0.906 | 0.787 | 0.842 | 0.879 | 0.963 |
| LoC (nos) <= 275 | 0.924 | 0.933 | 0.974 | 0.953 | 0.882 | 0.738 | 0.804 | 0.849 | 0.966 |

Spearman rho, ours vs published reference score (Ghost Echoes, Borg et al. 2024): 0.871.
Spearman rho, ours vs human dimensions (0 = best, so negative is good): Overall -0.824, Readability -0.668, Understandability -0.734, Complexity_inv 0.803, Modularization_inv 0.827. Reference score vs Overall: -0.790.
Runtime (match + review, one PMD batch): 17 s.

### Per project (UC2 F1 / AUC)

| project | n | ours UC2 F1 | ours AUC | reference UC2 F1 | reference AUC |
|---|---|---|---|---|---|
| argoUML | 74 | 0.788 | 0.948 | 0.759 | 0.951 |
| aoi | 70 | 0.907 | 0.971 | 0.880 | 0.942 |
| jsweet | 73 | 0.889 | 0.997 | 0.889 | 0.900 |
| junit4 | 73 | 0.000 | 0.861 | 0.000 | 0.889 |

reference = published reference score (Ghost Echoes, Borg et al. 2024), shipped in the replication package (Zenodo 12548630); comparison only.

### Per smell (share of files where the smell fires)

| smell | maintainable | non-maintainable | lift | total penalty |
|---|---|---|---|---|
| Complex Method | 10 (0.044) | 44 (0.721) | 16.518 | 45.4 |
| Overall Code Complexity | 7 (0.031) | 35 (0.574) | 18.770 | 19.7 |
| Deep, Nested Complexity | 3 (0.013) | 38 (0.623) | 47.552 | 38.8 |
| Complex Conditional | 11 (0.048) | 28 (0.459) | 9.556 | 17.5 |
| Brain Class | 6 (0.026) | 31 (0.508) | 19.396 | 62.3 |
| Large Method | 2 (0.009) | 35 (0.574) | 65.697 | 26.5 |
| Bumpy Road Ahead | 6 (0.026) | 28 (0.459) | 17.519 | 26.0 |
| Brain Method | 1 (0.004) | 26 (0.426) | 97.607 | 126.0 |
| Excess Number of Function Arguments | 4 (0.017) | 13 (0.213) | 12.201 | 10.6 |
| Low Cohesion | 6 (0.026) | 6 (0.098) | 3.754 | 4.2 |
| Code Duplication | 1 (0.004) | 8 (0.131) | 30.033 | 7.0 |
| Constructor Over-Injection | 0 (0.000) | 6 (0.098) | n/a | 2.7 |
| Lines of Code in a Single File | 0 (0.000) | 6 (0.098) | n/a | 4.0 |
| Number of Functions in a Single Module | 0 (0.000) | 3 (0.049) | n/a | 1.4 |

Missed non-maintainable files (score >= 9.0): 10; maintainable files flagged (score < 9.0): 7.


