# CodeHealth MCP — design

CodeHealth is an open maintainability metric for source files, exposed as an
MCP server (and CLI) for AI coding agents. It turns per-function and per-file
measurements into code smells and a 1-10 score, and compares versions of a
file so agents can tell whether an edit made code harder to maintain. The
public work that shaped it is listed in README.md, "Influences and
acknowledgements".

## Scope (MVP)
- Languages: every language lizard reads (31 readers: C/C++, C#, Java,
  JavaScript, TypeScript/TSX, Python, Go, Ruby, Kotlin, Swift, Scala, Rust,
  PHP, Dart, Lua, Perl, R, Objective-C, Fortran, Erlang, PL/SQL, COBOL,
  OCaml, F#, Solidity, Zig, GDScript, Vue, TTCN, Structured Text, ...).
  Python, JavaScript, TypeScript/TSX, Java and Go also have tree-sitter
  adapters for the smells only our own code measures (see Analyzers).
- Score: 1.0–10.0 per file; categories Healthy / Warning / Alert.
- Smells (function level): Complex Method, Large Method, Bumpy Road Ahead,
  Deep, Nested Complexity, Complex Conditional, Excess Number of Function
  Arguments, Brain Method.
- Smells (file level): Lines of Code in a Single File, Number of Functions in a
  Single Module, Low Cohesion (LCOM4, classes), Brain Class, Code Duplication.
- Config: `.codehealth/rules.json` (rule weights, thresholds,
  `matching_content_path` globs) plus `@codehealth(disable:"...")` comment
  directives.

## MCP tools

Every tool returns a JSON object as MCP structured content (plus the same
JSON as text).

| tool | purpose |
|---|---|
| `code_health_score` | file -> score + category |
| `code_health_review` | file -> score + findings (smell, function, line range, details, fix hint) |
| `pre_commit_code_health_safeguard` | git repo -> delta of staged/modified files vs HEAD, quality gate |
| `analyze_change_set` | git repo + base_ref -> per-file verdict improved/degraded/stable |
| `rules_config_validate` / `rules_config_list_thresholds` / `rules_config_set_rule` / `rules_config_set_threshold` | rules file management |
| `explain_code_health` | static docs on the model |

Delta verdicts compare old (git blob) vs new content per file; findings are
diffed by (smell, function) identity so agents see which smell got worse.

## Analyzers (open source first)

We use open-source analyzers wherever they measure what a smell needs and
keep our own tree-sitter code only for what neither tool provides. Every
review reports an `analyzers` field: which analyzers ran (with versions),
`unavailable_smells` for the file's language, `unavailable_features`
(comment directives) and notes. A missing analyzer never fails a tool.

| smell | provider | metric |
|---|---|---|
| Complex Method | lizard | cyclomatic complexity (CCN) |
| Large Method | lizard | function NLOC |
| Excess Number of Function Arguments | tree-sitter where we have an adapter, lizard elsewhere | parameter count (no `self`/`cls`; `@Override`/`@override`/TS `override` methods skipped) |
| Constructor Over-Injection | lizard (+ tree-sitter to recognise constructors where available) | parameter count |
| Deep, Nested Complexity | own tree-sitter (control structures only) for adapter languages; lizard `nd` extension as fallback for other brace languages; unavailable for other keyword/indentation languages | max nesting depth |
| Brain Method | lizard (+ nesting as above) | NLOC + CCN + nesting |
| Overall Code Complexity | lizard | mean CCN per function |
| Lines of Code in a Single File | lizard | file NLOC |
| Number of Functions in a Single Module | lizard | function inventory |
| Code Duplication | PMD CPD for every CPD language (primary; it normalises identifiers/literals for Java, C/C++, C#); plus own tree-sitter normalized tokens for Python, JavaScript, TypeScript, TSX and Go, whose CPD lexers cannot (renamed clones; works without PMD). Within file; cross-file between changed files in `pre_commit_code_health_safeguard` / `analyze_change_set`, informational | duplicated token runs mapped onto functions (CPD); share of each function's normalized tokens in common runs (tokens) |
| Brain Class | Java: PMD `GodClass`; other tree-sitter languages: our class structure + Brain Methods; other languages: module level only | WMC / LoC + function count |
| Bumpy Road Ahead | own tree-sitter | chunks of nested logic |
| Complex Conditional | own tree-sitter | logical operators per condition expression |
| Low Cohesion | own tree-sitter | LCOM4 |
| comment directives | own tree-sitter | `@codehealth(...)` comments |
| (details only) | lizard `cognitive` | cognitive complexity in every function finding's `details` |
| (details only) | PMD Java `TooManyMethods`, `ExcessiveParameterList`, `CognitiveComplexity`, `NPathComplexity`, `DataClass` | attached as `details.pmd` to overlapping function findings and listed in `pmd_violations`; no score penalty |

Function identity for delta matching stays "scope + ordinal": each lizard
function is matched to the innermost tree-sitter function with the same short
name that contains lizard's start line, and takes its identity, qualified name
and line range. lizard-only functions (no adapter, or no match) get lizard's
`::`/`.` scope plus an ordinal among equal labels, never a line number.

### Semantic differences (verified against our fixtures, lizard 1.26.0)
- **Nesting depth (`nd`)** counts more than control structures: the first
  `&&`/`||` inside a parenthesised condition adds a level, and in conditions
  without parentheses (Go) every `&&`/`||` adds one; `?`, `case`, `catch` are
  in its keyword set too. An `if` directly inside an `else if` branch is not
  counted. Fixture `process`: JS/TS/Java 5 -> 6, Go 5 -> 7; Python, TSX 5.
  Because of this, every language with a tree-sitter adapter (Python, JS,
  TS/TSX, Java, Go) uses our own depth: only `if`/loops/`switch`/`try`
  (and the language's equivalents) nest, `else if` chains do not. lizard
  `nd` is used only for brace languages without an adapter.
- `nd` closes a level only on `}`. In indentation- or `end`-delimited
  languages it never decreases (three sequential `if`s in Python or Ruby give
  3), so it is used only for brace languages. Python uses our tree-sitter
  nesting; Ruby, Lua, Fortran, Erlang, GDScript, COBOL, PL/SQL, OCaml, F#,
  ST report Deep, Nested Complexity and Brain Method as unavailable.
- **CCN**: same counts as our former code on all fixtures, except that a JS/TS
  default parameter (`step = 1`) adds 1.
- **NLOC**: identical to our former tree-sitter line counting on the fixtures
  (comments, blank lines and Python docstrings excluded).
- **Parameters**: lizard counts Python `self`/`cls` (we drop them), counts
  Java C-style array parameters (`double value[]`) wrongly (`f(double d, int n,
  double v[], Vec3 g[], int id[])` gives 2) and splits Go function-typed
  parameters (`f func(a, b int) int` adds 2). Adapter languages therefore
  count parameters from the tree-sitter parameter list (Go: one per name,
  JS destructuring pattern = 1, Python `*`/`/` separators skipped); lizard's
  count is the fallback. Operator `>` (fires at 5 with the default 4,
  constructors at 6). Methods marked as overrides (`@Override`, Python
  `@override`, TS `override`) are not reported: the supertype owns the
  signature (same practice as Sonar rule S107).
- `lizardboolcount` counts `bool` *type tokens*, not boolean operators, so it
  cannot back Complex Conditional; that stays on tree-sitter.
- **CPD** finds copy-paste (type-1) clones and, for lexers that support
  `--ignore-identifiers`/`--ignore-literals` (e.g. Java, C/C++, C#), renamed
  ones. The Python, ECMAScript, TypeScript and Go lexers ignore those flags
  (verified with PMD 7.29.0), so CPD misses renamed clones with changed
  literals there (the `dup_one`/`dup_two` fixtures). CPD similarity = share of
  each function's line span inside the duplicated block (both must reach
  `function_duplication_min_similarity_percentage`); minimum block size is
  `function_duplication_min_tokens` (default 50, inferred). Duplicated code
  outside functions is not reported.
- **Renamed clones** (`codehealth.duplication`, Python/JS/TS/TSX/Go): each
  function with at least `function_duplication_min_lines_of_code_for_check`
  NLOC (10, published default) becomes a normalized token stream from its tree-sitter
  node: named identifier nodes -> `ID`, string/number/boolean literals ->
  `LIT` (a whole template/f-string is one `LIT`), comments and nested
  functions dropped, keywords/operators/punctuation kept. Candidate pairs
  share a winnowed fingerprint (5-token k-grams, window 4; Schleimer et al.
  2003) through an inverted index; fingerprints shared by more than 50
  functions are boilerplate and skipped. Similarity = the smaller share of
  each side's tokens inside common runs of at least 5 tokens (stdlib
  `difflib.SequenceMatcher`); a pair needs >= 75% (published default) and at least
  `function_duplication_min_tokens` matched tokens, which keeps out tests
  whose lines are mostly one source string. CPD stays primary: a function
  pair it reports is not reported again (one finding per pair; `details.provider`
  is `pmd:cpd` or `tree-sitter:tokens`). Because exact copies are also token
  clones, Code Duplication stays available for these languages without PMD.
- **Brain Class (Java)** uses PMD's GodClass rule (WMC >= 47, ATFD > 5,
  TCC < 1/3); value = WMC, threshold 47.

### Low Cohesion (LCOM4) rule
LCOM4 (Hitz & Montazeri) counts connected components of a class's methods.
Our graph (own choice, following common LCOM4 practice):
- **Fields** are instance state only: non-static declared fields (Java, JS/TS
  class fields, Python class-body annotations such as dataclass fields) plus
  members used through `self`/`this`/the Go receiver that are not called and
  are not methods of the class. Class constants (Python plain class-body
  assignments, `static` fields) and inherited methods are not fields.
- **Methods** that take part exclude constructors, static/class methods,
  dunder methods and object-protocol methods (`equals`, `hashCode`,
  `toString`, ...). Accessor-only methods (a `get`/`set`/`is`/`has` name or a
  Python property, one statement, one field, no sibling calls) are not nodes;
  a call to one counts as a use of its field.
- Edges link a method to every field it reads or writes and to every sibling
  method it calls or references.
- Components that contain no field are dropped, so stateless methods and
  stateless helper clusters (overrides that ignore `self`, polymorphic
  adapters with a class-level `spec`) never count as a responsibility.
- A class without instance fields has no LCOM4. The smell needs LCOM4 >= 2
  and at least `class_lcom4_min_methods` methods inside stateful components.

### PMD runtime
PMD 7.29.0 is optional. `codehealth install-pmd` downloads the official
release (pinned SHA-256, archive paths checked) into `CODEHEALTH_PMD_HOME` or
the per-user data directory, where it is also located at runtime;
`CODEHEALTH_NO_PMD=1` disables it. It runs as a subprocess with an argument list, `CODEHEALTH_PMD_TIMEOUT`
(default 120 s), `--no-progress` and `--cache` (for `pmd check`; `pmd cpd`
has neither flag) under `$CODEHEALTH_CACHE_DIR` or `~/.cache/codehealth`.
**Batching** (`codehealth.enrich`): `review_sources` reviews many files with
one JVM per tool run: every file is copied into its own numbered
subdirectory of one scratch directory, CPD runs once per (lexer, minimum
tokens) group and `pmd check` once over all Java files; results are mapped
back by scratch path, and only duplication pairs inside one file count (the
same as a single-file run). The CLI (`codehealth review <dir>`), the
repository tools (old and new versions of every changed file) and the
benchmark use it; the timeout grows by one period per 100 files. The
benchmark went from 646 s to 13 s wall time for 290 files.
PMD only reads copies written into a private 0700 scratch directory there,
so it never follows paths or symlinks of the analysed repository; reports are
parsed with `defusedxml` / `json`. CPD is skipped (no JVM start) when a file
has fewer than two functions of the minimum size.

## Scoring model (own design, calibratable)
- Each finding has severity in (0, 1] from how far the measured value exceeds
  its threshold (log-scaled), times the rule weight.
- Function-level penalties are aggregated per function, then file penalty
  = sum over functions + file-level penalties, with diminishing returns:
  `score = 1 + 9 * exp(-k * penalty)`; k calibrated on a benchmark.
- Penalties are capped per function (`FUNCTION_PENALTY_CAP`), keyed by the
  function's stable identity (Java overloads are capped separately).
- **File size term** (own design): file NLOC beyond one acceptable function
  costs `FILE_SIZE_WEIGHT` (0.5) per `file_lines_of_code_for_warning` lines,
  i.e. `0.5 * max(0, nloc - function_lines_of_code_warning) /
  file_lines_of_code_for_warning`. Both scales are the published default per-language
  thresholds (unchanged); the term implements the documented "more LoC gives
  lower Code Health" below the warning tier, so small clean files stay at
  10.0 and a clean 600-line Java file scores about 9.6. It is scaled by the
  `Lines of Code in a Single File` rule weight (0 disables it), reported as
  `file_size_penalty`, and ignored by delta verdicts (growing a file is not a
  regression by itself). On the human-rated benchmark it raised AUC from
  0.943 to 0.975 (LoC <= 275 alone: 0.966), mostly by ranking the many
  smell-free files.
- Category bands (configurable): 10 optimal, Healthy >= 9.0, Warning >= 4.0,
  Alert < 4.0 (the bands used in the Ghost Echoes study; Code Red 2022 used
  8.0/4.0).
- Calibration: Schnappinger et al. human-rated dataset (304 Java classes,
  CC BY 4.0) via the Ghost Echoes replication package (Zenodo 12548630,
  CC BY 4.0); see `bench/README.md`. Targets: F1 for "maintainable" at
  score >= 9 and for flagging "unmaintainable" files, at least as good as
  the dataset's published reference score (Ghost Echoes, Borg et al. 2024),
  and better than the LoC <= 275 baseline. The published reference scores
  are used for comparison only, never as training labels; constants are
  tuned on the human labels with cross-validation (`bench.calibrate`).

## Stack
Python 3.12, `uv`, official `mcp` SDK (MCPServer, stdio), `lizard` (MIT),
optional PMD 7 (BSD-style, Java 8+), `tree-sitter` +
`tree-sitter-language-pack`, `defusedxml`, `pytest`. Licences:
THIRD_PARTY_NOTICES.md. Also a CLI (`codehealth score|review|delta|install-pmd`)
for CI use and debugging.

## Agent guidance baked into tool output
- Delta-first gates: fail on score drop >= 0.1 or a new smell in a touched function.
- Every finding: function, line range, measured value, threshold, fix hint.
- Recommend >= 9.5 for autonomous agent edits; small 3-5 step refactor loops.
- Refactoring validator: target smell gone, score not lower, no new smells.

## Improvement loop
1. Fixture corpus per language with expected findings (unit tests).
2. Benchmark harness against human-rated dataset -> correlation metric tracked
   in `bench/results.md` (`bench.run_bench`; `bench.ablate` and
   `bench.calibrate --cached` rescore its cached findings without re-parsing).
3. Dogfood: `scripts/dogfood.py` reviews `src/` and `bench/` through the MCP
   server and fails when a `src/` file is below 9.0; fix smells by
   simplifying code, never by disabling rules or raising thresholds.
