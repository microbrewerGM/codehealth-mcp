"""Unit tests for raw metrics (lizard + tree-sitter), severity and scoring."""

from __future__ import annotations

from pathlib import Path

from codehealth import score
from codehealth.analysis import measure_source, review_source
from codehealth.config import Rules
from codehealth.lang import parse_source
from codehealth.metrics import bumpy_road, lcom4
from codehealth.smells import severity
from codehealth.thresholds import defaults_for


def measured(source: str, path: str):
    return measure_source(source, Path(path), defaults_for(""))


def metrics(source: str, path: str) -> dict:
    return {f.name: f for f in measured(source, path).metrics.functions}


def fn(source: str, path: str, name: str):
    parsed = parse_source(source, path)
    return parsed, next(f for f in parsed.functions if f.name == name)


# ----- lizard: cyclomatic complexity -----------------------------------------------
def test_cc_counts_boolean_ops_case_catch_and_ternary_js():
    src = """function f(a, b) {
      if (a && b || a ?? b) {}
      switch (a) { case 1: break; case 2: break; default: break; }
      try {} catch (e) {}
      return a ? 1 : 2;
    }"""
    # lizard: 1 + if + && + || + ?? + 2 case + catch + ternary (`default` is not a case).
    assert metrics(src, "x.js")["f"].cyclomatic_complexity == 9


def test_cc_java_default_label_not_counted():
    src = "class A { void f(int a) { switch (a) { case 1: break; case 2: break; default: break; } } }"
    assert metrics(src, "A.java")["A.f"].cyclomatic_complexity == 3


def test_cc_python_and_go():
    src = "def f(a):\n    return [x for x in a if x] if a else None\n"
    assert metrics(src, "x.py")["f"].cyclomatic_complexity == 4  # ternary + for clause + if clause
    go = "package p\nfunc f(a int) { switch a { case 1: case 2: default: }; if a > 1 || a < 0 {} }\n"
    assert metrics(go, "x.go")["f"].cyclomatic_complexity == 5


def test_nested_functions_are_measured_separately():
    src = "def outer(a):\n    def inner(b):\n        if b:\n            return 1\n    return inner\n"
    found = metrics(src, "x.py")
    assert found["outer"].cyclomatic_complexity == 1
    assert found["outer.inner"].cyclomatic_complexity == 2
    assert found["outer.inner"].identity == "outer.inner"


# ----- nesting: tree-sitter for adapter languages, lizard nd as brace fallback -----------
def test_nesting_tree_sitter_for_adapter_languages():
    js = "function f(a, b) {\n  for (;;) { if (a) { if (b) { b(); } } }\n  if (a) { a(); }\n}\n"
    assert metrics(js, "x.js")["f"].nesting_depth == 3
    # Logical operators are not nesting (lizard nd says 3 here, 4 for the Go form).
    assert metrics("function f(a, b) { while (a) { if (a && b) { b(); } } }", "x.js")["f"].nesting_depth == 2
    go = "package p\nfunc f(a, b, c bool) {\n\tfor a {\n\t\tif a && b || c {\n\t\t\tg()\n\t\t}\n\t}\n}\n"
    assert metrics(go, "x.go")["f"].nesting_depth == 2
    java = "class A { void f(boolean a, boolean b) { while (a) { if (a && b) { g(); } } } }"
    assert metrics(java, "A.java")["A.f"].nesting_depth == 2
    # Sequential ifs: lizard's nd never closes a level in Python, so tree-sitter measures it.
    py = "def f(a, b, c):\n    if a:\n        x = 1\n    if b:\n        y = 2\n    if c:\n        z = 3\n"
    assert metrics(py, "x.py")["f"].nesting_depth == 1


def test_else_if_chain_does_not_add_nesting():
    src = "function f(a) { if (a == 1) {} else if (a == 2) {} else if (a == 3) { a(); } }"
    assert metrics(src, "x.js")["f"].nesting_depth == 1
    py = "def f(a):\n    if a:\n        pass\n    elif a > 1:\n        for x in a:\n            pass\n"
    assert metrics(py, "x.py")["f"].nesting_depth == 2


def test_nesting_unavailable_for_keyword_delimited_languages_without_adapter():
    ruby = "def f(a)\n  if a\n    1\n  end\n  if a\n    2\n  end\nend\n"
    assert metrics(ruby, "x.rb")["f"].nesting_depth is None


# ----- lizard -> tree-sitter identity mapping -----------------------------------------
def test_lizard_functions_take_tree_sitter_identities():
    src = """class A {
  @Override
  public String toString() { return "a"; }
  void f(int a, int b, int c, int d, int e) {}
  void f(int a, int b, int c, int d, int e, int g) {}
  class In { void g() {} }
}
"""
    rows = [(f.name, f.identity, f.start_line, f.syntax is not None) for f in measured(src, "A.java").metrics.functions]
    assert rows == [
        ("A.toString", "A.toString", 2, True),  # tree-sitter line range includes the annotation
        ("A.f", "A.f", 4, True),
        ("A.f", "A.f#1", 5, True),
        ("A.In.g", "A.In.g", 6, True),
    ]


def test_lizard_only_functions_get_scope_and_ordinal_identities():
    ruby = "class Svc\n  def run(a)\n    a\n  end\nend\ndef run(b)\n  b\nend\n"
    first = [(f.name, f.identity, f.syntax) for f in measured(ruby, "svc.rb").metrics.functions]
    assert first == [("run", "run", None), ("run", "run#1", None)]
    shifted = [f.identity for f in measured("\n\n# moved\n" + ruby, "svc.rb").metrics.functions]
    assert shifted == ["run", "run#1"]  # no line numbers in identities


def test_constructor_detection_from_lizard_names():
    cs = "class Svc {\n  public Svc(int a, int b, int c, int d, int e, int f) { }\n  public void Run(int a) { }\n}\n"
    found = metrics(cs, "Svc.cs")
    assert found["Svc.Svc"].is_constructor and not found["Svc.Run"].is_constructor
    rb = "class Svc\n  def initialize(a)\n    @a = a\n  end\nend\n"
    assert metrics(rb, "svc.rb")["initialize"].is_constructor


def test_bumpy_road_counts_separate_chunks():
    src = """def f(a, b):
    if a:
        if b:
            pass
    x = 1
    while a:
        for i in b:
            if i:
                pass
    if a:
        pass
"""
    parsed, f = fn(src, "x.py", "f")
    assert bumpy_road(parsed, f, 2) == [2, 3]


def test_adjacent_nested_statements_form_one_bump():
    src = "def f(a, b):\n    if a:\n        if b:\n            pass\n    for x in a:\n        if x:\n            pass\n"
    parsed, f = fn(src, "x.py", "f")
    assert bumpy_road(parsed, f, 2) == [2]


def test_lcom4_python_components_and_calls():
    src = """class A:
    def a1(self): return self.x
    def a2(self): return self.x + self.helper()
    def helper(self): return 1
    def b1(self): return self.y
    def static(self): return 2
"""
    parsed = parse_source(src, "x.py")
    cls = parsed.classes[0]
    # {a1, a2, helper} share x / call; {b1}; `static` touches nothing and is ignored.
    assert lcom4(cls) == 2


def test_lcom4_go_receiver_groups():
    src = "package p\ntype S struct{ a, b int }\nfunc (s *S) A() int { return s.a }\nfunc (s *S) B() int { return s.a + s.b }\n"
    parsed = parse_source(src, "x.go")
    assert [c.name for c in parsed.classes] == ["S"]
    assert lcom4(parsed.classes[0]) == 1


def test_loc_excludes_blank_and_comment_lines():
    src = "def f(a):\n    # comment\n\n    x = a  # trailing\n    return x\n"
    assert metrics(src, "x.py")["f"].lines_of_code == 3


def test_arguments_exclude_self_and_count_go_names():
    src = "class A:\n    def m(self, a, *args, b=1, **kw):\n        pass\n"
    assert metrics(src, "x.py")["A.m"].arguments == 4
    assert metrics("package p\nfunc f(a, b int, c ...string) {}\n", "x.go")["f"].arguments == 3


def test_cognitive_complexity_in_finding_details():
    src = "def f(a, b, c, d, e):\n    if a:\n        for x in b:\n            if x:\n                return 1\n"
    findings = review_source(src, Path("x.py")).findings
    finding = next(f for f in findings if f.smell == "Excess Number of Function Arguments")
    assert finding.details["cognitive_complexity"] == 6  # 1 + 2 + 3 (SonarSource nesting increments)


def _long_brain_function() -> str:
    lines = ["def brain(a, b):"]
    lines += ["    if a:", "        for x in b:", "            while x:", "                if x > 1:", "                    x -= 1"]
    lines += [f"    a = a + {i} if a > {i} else a" for i in range(70)]
    lines += ["    return a"]
    return "\n".join(lines) + "\n"


def test_brain_method_absorbs_complex_method():
    review = review_source(_long_brain_function(), Path("b.py"))
    smells = {f.smell for f in review.findings}
    assert "Brain Method" in smells
    assert "Complex Method" not in smells
    assert {"Large Method", "Deep, Nested Complexity"} <= smells


def test_brain_class_with_lowered_thresholds():
    thresholds = defaults_for("python") | {"brain_class_lines_of_code": 50, "brain_class_function_count": 1}
    review = review_source(_long_brain_function(), Path("b.py"), Rules(thresholds=thresholds))
    brain_class = [f for f in review.findings if f.smell == "Brain Class"]
    assert len(brain_class) == 1 and brain_class[0].function == "<module>"


def test_severity_is_log_scaled_and_bounded():
    assert severity(9, 9) == 0.2
    assert severity(18, 9) < severity(36, 9) <= 1.0
    assert severity(100, 9, alert=100) == 1.0
    assert severity(1000, 9) == 1.0


def test_score_formula_and_bands():
    assert score.score_from_penalty(0) == 10.0
    assert score.score_from_penalty(1) == round(1 + 9 * 2.718281828 ** -score.K, 2)
    assert score.category(9.0) == "Healthy"
    assert score.category(8.99) == "Warning"
    assert score.category(4.0) == "Warning"
    assert score.category(3.99) == "Alert"
    assert score.is_optimal(10.0) and not score.is_optimal(9.99)


def test_python_docstrings_are_not_code_lines():
    src = 'def f():\n    """Doc.\n\n    More.\n    """\n    return 1\n'
    m = measured(src, "x.py").metrics
    assert m.lines_of_code == 2 and m.functions[0].lines_of_code == 2


def test_overloads_get_their_own_penalty_cap():
    from codehealth.smells import Finding

    def finding(identity: str) -> Finding:
        return Finding("Complex Method", "function", "A.f", 1, 2, 9, 9, 1.0, "", "", identity=identity)

    one = [finding("A.f")] * 10
    two = [finding("A.f")] * 5 + [finding("A.f#1")] * 5
    assert score.total_penalty(one) == score.FUNCTION_PENALTY_CAP
    assert score.total_penalty(two) == 2 * min(5 * score.SMELL_IMPACT["Complex Method"], score.FUNCTION_PENALTY_CAP)
