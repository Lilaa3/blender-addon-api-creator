from blender_api_lib import registry
from conftest import V, create_addon, reg, target


class TestUnregisterSafety:
    def test_nonexistent_addon(self):
        registry.get_registry().unregister_addon("path_that_does_not_exist")

    def test_nonexistent_system(self):
        addon = create_addon("SafeAddon", {}, "safe_addon")
        addon.unregister_system(("nonexistent",))

    def test_double_unregister(self):
        addon = create_addon("DoubleUnreg", {}, "double_unreg")
        addon.unregister_addon()
        addon.unregister_addon()

    def test_override_removed_after_unregister(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="compute", version=V(1, 0, 0))
        def compute():
            return "original"

        @s_b.override(target("compute"))
        def compute_override():
            return "overridden"

        reg((a, s_a), (b, s_b))
        assert compute() == "overridden", "Override should be active"

        b.unregister_addon()
        assert (
            compute() == "original"
        ), "After override addon unregisters, original must run"
