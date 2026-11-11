"""Excess Number of Function Arguments: counting and the `> 4` operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from codehealth.analysis import measure_source, review_source
from codehealth.thresholds import defaults_for

EXCESS = "Excess Number of Function Arguments"


def arguments(source: str, path: str) -> dict[str, int]:
    m = measure_source(source, Path(path), defaults_for(""))
    return {f.name: f.arguments for f in m.metrics.functions}


def excess(source: str, path: str) -> list[str]:
    return [f.function for f in review_source(source, Path(path)).findings if f.smell == EXCESS]


def test_java_c_style_array_parameters_are_counted():
    # lizard 1.26 counts 2 here: `double value[]` style declarators confuse it.
    src = "class A { void f(double d, int n, double value[], Vec3 grad[], int id[]) {} }"
    assert arguments(src, "A.java")["A.f"] == 5
    assert excess(src, "A.java") == ["A.f"]


def test_go_function_typed_parameter_is_one_argument():
    src = "package p\nfunc G(m map[string]int, f func(a, b int) int) {}\nfunc K(a int, b, c string, d ...int) (x, y int) {}\n"
    assert arguments(src, "x.go") == {"G": 2, "K": 4}


def test_python_self_cls_and_separators():
    src = (
        "class A:\n"
        "    def m(self, a, *args, b=1, **kw):\n        pass\n"
        "    def n(self, a, /, b, *, c):\n        pass\n"
        "    @classmethod\n    def c(cls, a):\n        pass\n"
        "    @staticmethod\n    def s(a, b):\n        pass\n"
    )
    assert arguments(src, "x.py") == {"A.m": 4, "A.n": 3, "A.c": 1, "A.s": 2}


def test_js_destructured_patterns_count_once():
    assert arguments("function f({a, b, c}, [d, e], g = h(1, 2), ...rest) {}", "x.js") == {"f": 4}


@pytest.mark.parametrize("count, fires", [(4, False), (5, True)])
def test_threshold_is_strictly_greater_than_four(count, fires):
    params = ", ".join(f"a{i}" for i in range(count))
    assert bool(excess(f"def f({params}):\n    return 1\n", "x.py")) is fires


def test_constructor_threshold_is_strictly_greater_than_five():
    five = "class A { A(int a, int b, int c, int d, int e) {} }"
    six = "class A { A(int a, int b, int c, int d, int e, int f) {} }"
    smells = lambda src: {f.smell for f in review_source(src, Path("A.java")).findings}  # noqa: E731
    assert smells(five) == set()
    assert smells(six) == {"Constructor Over-Injection"}


def test_overrides_do_not_own_their_signature():
    java = "class A implements R { @Override public Object get(Object a, Object b, int c, int d, boolean e) { return a; } }"
    py = "from typing import override\nclass A(B):\n    @override\n    def f(self, a, b, c, d, e):\n        return a\n"
    ts = "class A extends B { override f(a: number, b: number, c: number, d: number, e: number) {} }"
    assert excess(java, "A.java") == []
    assert excess(py, "x.py") == []
    assert excess(ts, "x.ts") == []
