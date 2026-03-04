from blender_api_lib.api_types import RuntimeExposedHook, RuntimeTargetFunction
from conftest import create_system, target, reg, V


class TestOverride:
    def test_override_replaces_main(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="compute", version=V(1, 0, 0))
        def compute():
            return "original"

        @s_b.override(target("compute"))
        def compute_override():
            return "overridden"

        reg((a, s_a), (b, s_b))
        assert compute() == "overridden", "Override should replace main"

    def test_get_override_reports_overrider(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="compute", version=V(1, 0, 0))
        def compute():
            return "original"

        @s_b.override(target("compute"))
        def compute_override():
            return "overridden"

        reg((a, s_a), (b, s_b))
        func_name, _sys, addon_name = s_a.get_override("compute")
        assert (
            addon_name == "Addon B"
        ), "get_override should report the overriding addon"

    def test_self_override_ignored(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))

        @s_a.function(name="self_fn", version=V(1, 0, 0))
        def self_fn():
            return "original"

        @s_a.hook(target("self_fn"), when="override")
        def self_override():
            return "self-overridden"

        a.register_system(s_a)
        assert self_fn() == "original", "Self-override must be ignored"

    def test_no_override_reports_original(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))

        @s_a.function(name="raw")
        def raw():
            return 42

        a.register_system(s_a)
        func_name, sys, addon_name = s_a.get_override("raw")
        assert addon_name == "Addon A", "No override means original addon is reported"
        assert sys == ("core",), "No override means original system is reported"
        assert func_name == "raw", "Function name should match"

    def test_expose_api_as_hookable(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", ("ext",))
        c, s_c = create_system("Addon C", {}, "addon_c", None)
        order = []

        @s_a.function(name="base_fn", version=V(1, 0, 0))
        def base_fn():
            order.append("original")
            return "original"

        @s_b.override(
            target("base_fn"),
            expose_api_as=RuntimeExposedHook(name="b_override", version=V(1, 0, 0)),
        )
        def b_override():
            order.append("b_override")
            return "b_override"

        @s_c.hook(
            RuntimeTargetFunction("Addon B", "b_override", ("ext",)), when="before"
        )
        def b_before():
            order.append("b_before")

        reg((a, s_a), (b, s_b), (c, s_c))

        result = base_fn()

        assert result == "b_override", "Override should be active"
        assert order == [
            "b_before",
            "b_override",
        ], "Hooks should run in correct order"
