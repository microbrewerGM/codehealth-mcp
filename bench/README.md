# Benchmark: CodeHealth vs human maintainability ratings

The benchmark scores the Java classes that professional developers rated for
maintainability and checks how well a score >= 9 separates maintainable
files (human `Overall` <= 1) from the rest. Current results:
[results.md](results.md) (aggregate metrics only).

Headline (290 files): UC1 F1 0.963, UC2 F1 0.857, AUC 0.975.

## Data (not in this repository)

Point `CODEHEALTH_BENCH_DATA` at a directory laid out like this:

```text
$CODEHEALTH_BENCH_DATA/
  ghost-echoes/maintainability_data.csv
  sources/argoUML/   sources/aoi/   sources/jsweet/   sources/junit4/
```

1. Download `maintainability_data.csv` from the Ghost Echoes replication
   package, https://zenodo.org/records/12548630, into `ghost-echoes/`.
2. Clone the four public repositories into `sources/<project>`; the commit
   used for each is pinned in [revisions.json](revisions.json):

   ```sh
   cd "$CODEHEALTH_BENCH_DATA/sources"
   git clone https://github.com/argouml-tigris-org/argouml argoUML
   git clone https://github.com/ArtOfIllusion/ArtOfIllusion aoi
   git clone https://github.com/cincheo/jsweet jsweet
   git clone https://github.com/junit-team/junit4 junit4
   ```

   The benchmark reads files at the pinned commits with `git cat-file`; the
   checkouts need full history, not a particular branch. The fifth project
   of the dataset (Diary Management) is not public and is excluded.

## Run

```sh
export CODEHEALTH_BENCH_DATA=/path/to/data
uv run python -m bench.run_bench              # rewrites results.md / results.json
uv run python -m bench.ablate                 # per-smell ablation from the cached findings
uv run python -m bench.calibrate --cached     # cross-validated scoring constants
uv run python -m bench.select_revisions       # re-pick revisions.json (slow)
```

Per-file rows (human labels, reference scores, our scores) are written to
`bench/.cache/`, which is not committed.

The dataset also carries a published reference score per file (CSV column
`Code_Health`), from the Ghost Echoes study (Borg et al. 2024). The
benchmark reports it next to ours as a comparison baseline only; nothing is
fitted to it.

## Attribution (CC BY 4.0)

The benchmark uses, and the aggregate metrics in `results.md` and
`results.json` are derived from, these datasets, both licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

- Markus Schnappinger, Arnaud Fietzke, Alexander Pretschner. "A Software
  Maintainability Dataset". figshare, 2020. DOI 10.6084/m9.figshare.12801215.v3.
  Paper: "Defining a Software Maintainability Dataset: Collecting, Aggregating
  and Analysing Expert Evaluations of Software Maintainability", ICSME 2020.
- Markus Borg, Marwa Ezzouhri, Adam Tornhill. Replication package for "Ghost
  Echoes Revealed: Benchmarking Maintainability Metrics and Machine Learning
  Predictions Against Human Assessments" (ICSME 2024). Zenodo, DOI
  10.5281/zenodo.12548630.

Changes: we compute our own scores for the rated files and report only
aggregate metrics (precision, recall, F1, AUC, rank correlations, per-smell
counts); no rows of the datasets are redistributed.
