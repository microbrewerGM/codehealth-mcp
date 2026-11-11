"""LCOM4 rule: only methods that use instance state count (see DESIGN.md, Low Cohesion)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codehealth.analysis import review_file
from codehealth.lang import parse_source
from codehealth.metrics import Cohesion, cohesion, lcom4

SRC = Path(__file__).resolve().parents[1] / "src" / "codehealth"


def only_class(src: str, path: str):
    return parse_source(src, path).classes[0]


@pytest.mark.parametrize("name", ["lang/go.py", "lang/java.py", "lang/javascript.py", "lang/python.py"])
def test_our_stateless_adapters_have_no_low_cohesion(name):
    review = review_file(SRC / name)
    assert not [f for f in review.findings if f.smell == "Low Cohesion"]


def test_stateless_polymorphic_python_class_has_no_lcom4():
    src = """class Adapter(Base):
    spec = make_spec()

    def name(self, node):
        return self.helper(node)

    def params(self, node):
        return self.parameter_nodes(node)

    def refs(self, node):
        return [n for n in self.iter_own(node)]

    def finish(self, items):
        return items
"""
    cls = only_class(src, "x.py")
    assert cls.fields == set()  # `spec` is a class constant; inherited methods are not fields
    assert cohesion(cls).lcom4 == 0


def test_static_dunder_and_class_methods_are_ignored():
    src = """class A:
    def __init__(self):
        self.x = 0
        self.y = 0
    def a1(self): return self.x
    def a2(self): self.x += 1
    def __repr__(self): return str(self.y)
    @staticmethod
    def s(): return 1
    @classmethod
    def c(cls): return cls.other
"""
    cls = only_class(src, "x.py")
    assert set(cls.member_refs) == {"a1", "a2"}
    assert cohesion(cls).lcom4 == 1


def test_stateless_helper_clusters_are_dropped():
    src = """class A:
    def a1(self): return self.x + 1
    def a2(self): return self.x * 2
    def b1(self): return self.b2()
    def b2(self): return 3
"""
    # {b1, b2} call each other but touch no field: not a responsibility of their own.
    assert cohesion(only_class(src, "x.py")) == Cohesion(lcom4=1, methods=2)


def test_accessor_only_methods_do_not_split_the_class():
    src = """public class A {
    private int a;
    private int c;
    public int one() { return a + 1; }
    public int two() { return a * 2; }
    public int getC() { return c; }
    public void setC(int v) { this.c = v; }
    public static int util() { return 4; }
    public String toString() { return "" + c; }
}"""
    cls = only_class(src, "A.java")
    assert cls.accessors == {"getC", "setC"}
    assert lcom4(cls) == 1


def test_call_to_an_accessor_counts_as_its_field():
    src = """public class A {
    private int a;
    private int c;
    public int one() { return a + getC(); }
    public int two() { return c * 2; }
    public int getC() { return c; }
}"""
    assert lcom4(only_class(src, "A.java")) == 1


def test_javascript_class_without_instance_state():
    src = """class Child extends Base {
  static kind = "x";
  name(node) { return this.helper(node); }
  params(node) { return this.paramNodes(node); }
  refs(node) { return this.walk(node); }
  finish(items) { return items; }
}"""
    cls = only_class(src, "x.js")
    assert cls.fields == set() and lcom4(cls) == 0


def test_javascript_fields_from_this_and_declarations():
    src = """class Mixed {
  count = 0;
  incA() { this.a += 1; }
  incB() { this.b += this.a; }
  incX() { this.x += this.count; }
  incY() { this.y += this.x; }
}"""
    cls = only_class(src, "x.js")
    assert cls.fields == {"a", "b", "x", "y", "count"}
    assert lcom4(cls) == 2


def test_go_method_calls_link_but_are_not_fields():
    src = """package p
type S struct{ a, b int }
func (s *S) A() int { return s.a }
func (s *S) B() int { return s.b + s.A() }
"""
    cls = only_class(src, "x.go")
    assert cls.fields == {"S.a", "S.b"}
    assert lcom4(cls) == 1
