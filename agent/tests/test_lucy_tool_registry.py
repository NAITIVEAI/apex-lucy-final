import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core.tool_registry import (
    build_function_registry,
    build_lucy_function_list,
    toolset_signature,
)


def _named(name):
    def fn(*args, **kwargs):
        return name
    fn.__name__ = name
    return fn


class BuildLucyFunctionListTests(unittest.TestCase):
    def test_no_dynamics_no_handoff(self):
        helpers = [_named("a"), _named("b")]
        result = build_lucy_function_list(
            setup_dynamics_fn=None,
            core_helpers=helpers,
            setup_handoff_fn=None,
        )
        self.assertEqual([f.__name__ for f in result], ["a", "b"])

    def test_with_dynamics_and_handoff(self):
        helpers = [_named("h1")]
        dyn = lambda: [_named("d1"), _named("d2")]
        handoff = lambda: [_named("ho1")]
        result = build_lucy_function_list(
            setup_dynamics_fn=dyn,
            core_helpers=helpers,
            setup_handoff_fn=handoff,
        )
        self.assertEqual([f.__name__ for f in result], ["d1", "d2", "h1", "ho1"])

    def test_handoff_failure_is_swallowed(self):
        def bad_handoff():
            raise RuntimeError("boom")
        helpers = [_named("h1")]
        result = build_lucy_function_list(
            setup_dynamics_fn=None,
            core_helpers=helpers,
            setup_handoff_fn=bad_handoff,
        )
        self.assertEqual([f.__name__ for f in result], ["h1"])

    def test_dynamics_first_then_helpers_then_handoff(self):
        # Order matters — preserves the ordering the prior implementation emitted.
        result = build_lucy_function_list(
            setup_dynamics_fn=lambda: [_named("d1")],
            core_helpers=[_named("c1"), _named("c2")],
            setup_handoff_fn=lambda: [_named("h1")],
        )
        self.assertEqual([f.__name__ for f in result], ["d1", "c1", "c2", "h1"])


class BuildFunctionRegistryTests(unittest.TestCase):
    def test_basic_registry(self):
        funcs = [_named("a"), _named("b")]
        registry = build_function_registry(funcs)
        self.assertEqual(set(registry), {"a", "b"})
        self.assertIs(registry["a"], funcs[0])

    def test_skips_non_callable(self):
        funcs = [_named("a"), "not_callable", 42]
        registry = build_function_registry(funcs)
        self.assertEqual(set(registry), {"a"})

    def test_duplicate_overwrites_with_last(self):
        first = _named("dup")
        second = _named("dup")
        registry = build_function_registry([first, second])
        self.assertIs(registry["dup"], second)

    def test_unnamed_callable_skipped(self):
        class Unnamed:
            __name__ = ""

            def __call__(self):
                return None

        registry = build_function_registry([Unnamed()])
        self.assertEqual(registry, {})


class ToolsetSignatureTests(unittest.TestCase):
    def test_stable_across_orderings(self):
        a, b, c = _named("a"), _named("b"), _named("c")
        self.assertEqual(toolset_signature([a, b, c]), toolset_signature([c, a, b]))

    def test_changes_with_new_tool(self):
        a, b = _named("a"), _named("b")
        self.assertNotEqual(toolset_signature([a]), toolset_signature([a, b]))

    def test_skips_non_callable(self):
        a = _named("a")
        self.assertEqual(toolset_signature([a]), toolset_signature([a, "not_callable"]))

    def test_returns_hex_digest(self):
        sig = toolset_signature([_named("a")])
        self.assertEqual(len(sig), 64)
        int(sig, 16)  # raises if not hex


if __name__ == "__main__":
    unittest.main()
