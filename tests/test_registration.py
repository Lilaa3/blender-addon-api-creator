import pytest
from blender_api_lib import client, registry
from conftest import create_addon, create_system


class TestRegistration:
    def test_addon_registration(self):
        addon = create_addon("TestAddon", {"version": "1.0"}, "test_addon")
        assert registry.get_registry()._get_addon("test_addon"), "Addon not registered"
        assert registry.get_registry()._get_addons_by_name(
            "TestAddon"
        ), "Addon not registered by name"

    def test_system_registration(self):
        _a, s = create_system("Addon A", {}, "addon_a", ("core",), True)
        assert registry.get_registry()._get_system(
            "addon_a", ("core",)
        ), "System not registered"
        assert registry.get_registry()._get_systems(
            "Addon A", ("core",)
        ), "System not registered by name"

    def test_multiple_systems_same_addon(self):
        addon = create_addon("MultiSystem", {}, "multi_sys")
        s1 = client.APISystem(system_name=("system", "one"), _addon_path="multi_sys")
        s2 = client.APISystem(system_name=("system", "two"), _addon_path="multi_sys")
        addon.register_system(s1)
        addon.register_system(s2)
        assert len(addon.systems) == 2, "Systems not registered on addon"
        assert (
            len(registry.get_registry()._get_runtime_addon("multi_sys").systems) == 2
        ), "Systems not in registry"

    def test_different_systems_multiple_addons(self):
        a1, s1 = create_system("Addon A", {}, "addon_a", ("core",), True)
        a2, s2 = create_system("Addon B", {}, "addon_b", ("core",), True)
        assert registry.get_registry()._get_system(
            "addon_a", ("core",)
        ), "System not registered"
        assert registry.get_registry()._get_system("addon_b", ("core",))

    def test_unnamed_system(self):
        _a, s = create_system("Addon A", {}, "addon_a", None, True)
        assert s.system_name is None, "Unnamed system should have None as name"

    def test_function_in_system_after_register(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        @s.function(name="my_fn")
        def my_fn():
            return 1

        a.register_system(s)
        data = registry.get_registry()._get_system("addon_a", ("core",))
        assert "my_fn" in data["functions"], "Function should appear in system data"

    def test_reregister_system(self):
        import example_exposed_module

        a, s = create_system("Addon A", {}, "addon_a", ("core",))
        s.expose_module(example_exposed_module)
        a.register_system(s)
        assert (
            client.get_system_module("Addon A", ("core",)) is not None
        ), "Module should be exposed"

        s = client.APISystem(system_name=("core",), _addon_path="addon_a")
        a.register_system(s)
        assert (
            client.get_system_module("Addon A", ("core",)) is None
        ), "Module should not be exposed after reregister"

    def test_reregister_addon(self):
        import example_exposed_module

        a, s = create_system("Addon A", {}, "addon_a", ("core",), False)
        s.expose_module(example_exposed_module)
        a.register_system(s)

        assert (
            client.get_system_module("Addon A", ("core",)) is not None
        ), "Module should be exposed"

        a, s = create_system("Addon A", {}, "addon_a", ("core",), False)
        assert registry.get_registry()._get_addon(
            "addon_a"
        ), "Addon should be registered"
        a.register_system(s)
        assert (
            client.get_system_module("Addon A", ("core",)) is None
        ), "Module should not be exposed after reregister"
