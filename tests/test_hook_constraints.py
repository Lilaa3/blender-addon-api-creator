from blender_api_lib.api_types import RuntimeTargetFunction, RuntimeTargetAddon
from conftest import create_system, target, reg, V


class TestHookConstraints:
    def test_yields_to_present(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        c, s_c = create_system("Addon C", {}, "addon_c", ("ext",))
        order = []

        @s_a.function(name="work", version=V(1, 0, 0))
        def work():
            order.append("main")

        @s_c.function(name="work", version=V(1, 0, 0))
        def c_work():
            pass

        @s_b.hook(
            target("work"),
            when="before",
            yields_to=[RuntimeTargetFunction("Addon C", "work", ("ext",))],
        )
        def b_before():
            order.append("addon_b_before")

        reg((a, s_a), (b, s_b), (c, s_c))
        work()
        assert "addon_b_before" not in order

    def test_yields_to_absent(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        order = []

        @s_a.function(name="work", version=V(1, 0, 0))
        def work():
            order.append("main")

        @s_b.hook(
            target("work"),
            when="before",
            yields_to=[RuntimeTargetFunction("Missing Addon", "work", ("ext",))],
        )
        def b_before():
            order.append("addon_b_before")

        reg((a, s_a), (b, s_b))
        work()
        assert "addon_b_before" in order, "Hook should not yield to missing addon"

    def test_requires_provider_present(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        c, s_c = create_system("Addon C", {}, "addon_c", ("provider",), True)
        called = []

        @s_a.function(name="work", version=V(1, 0, 0))
        def work():
            pass

        @s_b.hook(
            target("work"),
            when="before",
            requires_provider=[RuntimeTargetAddon("Addon C", ("provider",))],
        )
        def b_before():
            called.append(True)

        reg((a, s_a), (b, s_b))
        work()
        assert called

    def test_requires_provider_absent(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        called = []

        @s_a.function(name="work", version=V(1, 0, 0))
        def work():
            pass

        @s_b.hook(
            target("work"),
            when="before",
            requires_provider=[RuntimeTargetAddon("Missing Addon", ("provider",))],
        )
        def b_before():
            called.append(True)

        reg((a, s_a), (b, s_b))
        work()
        assert not called
