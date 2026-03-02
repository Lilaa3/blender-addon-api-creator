import sys
import pytest

from blender_api_lib import client, registry
from blender_api_lib.types import (
    APIContext,
    RuntimeTargetFunction,
    RuntimeTargetAddon,
    APIVersion,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """
    This fixture runs before EVERY test.
    It completely wipes the global registry and API singletons to ensure
    a clean slate, preventing tests from polluting each other.
    """
    # Clear API singletons
    client.API_ADDON_SINGLETON = None
    client.SYSTEMS.clear()

    # Clear Registry global state
    if registry._GLOBAL_KEY in sys.modules:
        del sys.modules[registry._GLOBAL_KEY]

    # Force a fresh registry initialization
    registry.register_registry(reload=True)

    yield  # The test runs here

    # Teardown (optional, but good practice)
    client.API_ADDON_SINGLETON = None
    client.SYSTEMS.clear()
    if registry._GLOBAL_KEY in sys.modules:
        del sys.modules[registry._GLOBAL_KEY]


def create_addon(name: str, bl_info: dict, addon_path: str):
    addon = client.APIAddon(name=name, bl_info=bl_info, addon_path=addon_path)
    addon.register_addon()
    return addon


def create_system(
    name: str, bl_info: dict, addon_path: str, system_name: str, register: bool = False
):
    addon = create_addon(name=name, bl_info=bl_info, addon_path=addon_path)
    sys = client.APISystem(system_name=system_name, _addon_path=addon_path)
    if register:
        addon.register_system(sys)
    return addon, sys


class TestBasicRegistration:
    def test_addon_registration(self):
        addon = create_addon("TestAddon", {"version": "1.0"}, "test_addon")
        assert registry.get_registry()._get_addon("test_addon"), "Addon not registered"
        assert registry.get_registry()._get_addons_by_name(
            "TestAddon"
        ), "Addon not registered"

    def test_system_registration(self):
        _addon, sys_a = create_system("Addon A", {}, "addon_a", ("core",), True)
        assert registry.get_registry()._get_system(
            "addon_a", ("core",)
        ), "System not registered"
        assert registry.get_registry()._get_systems(
            "Addon A", ("core",)
        ), "System not registered"

    def test_multiple_systems_same_addon(self):
        addon = create_addon("MultiSystem", {}, "multi_sys")
        sys1 = client.APISystem(system_name=("system", "one"), _addon_path="multi_sys")
        sys2 = client.APISystem(system_name=("system", "two"), _addon_path="multi_sys")
        addon.register_system(sys1)
        addon.register_system(sys2)
        assert len(addon.systems) == 2, "Systems not registered"
        assert (
            len(registry.get_registry()._get_runtime_addon("multi_sys").systems) == 2
        ), "Systems not registered"

    def test_unnamed_system(self):
        _addon, sys_a = create_system("Addon A", {}, "addon_a", None, True)
        assert sys_a.system_name is None


def test_lifecycle_registration():
    addon_a, sys_a = create_system("Addon A", {}, "addon_a", ("core",))
    addon_b, sys_b = create_system("Addon B", {}, "addon_b", None)

    ready_called = exit_called = False

    @sys_b.on_ready(RuntimeTargetAddon("Addon A", ("core",)))
    def sys_a_ready():
        nonlocal ready_called
        ready_called = True
        print("[Addon B] Addon A has been registered!")

    @sys_b.on_exit(RuntimeTargetAddon("Addon A", ("core",)))
    def sys_a_exit():
        nonlocal exit_called
        exit_called = True
        print("[Addon B] Addon A has been unregistered!")

    addon_b.register_system(sys_b)
    addon_a.register_system(sys_a)

    assert not ready_called, "Addon B should not be running its ready function yet"
    assert not exit_called, "Addon B should not be running its exit function yet"
    sys_a.finalize_system()

    assert ready_called, "Addon B should have run its ready function"
    assert not exit_called, "Addon B should not be running its exit function yet"
    ready_called = exit_called = False

    addon_a.unregister_system(sys_a.system_name)

    assert (
        not ready_called
    ), "Addon B should not be running its ready function on unregister"
    assert exit_called, "Addon B should have run its exit function on unregister"
    ready_called = exit_called = False

    addon_a, sys_a = create_system("Addon A", {}, "addon_a", ("core",), True)
    addon_a.unregister_addon()

    assert (
        not ready_called
    ), "Addon B should not be running its ready function on addon unregister"
    assert exit_called, "Addon B should have run its exit function on addon unregister"


def test_basic_function_api():
    addon, sys_a = create_system("Addon A", {}, "addon_a", ("core",))

    @sys_a.function(name="greet")
    def greet(name: str):
        return f"Hello, {name}!"

    addon.register_system(sys_a)

    assert sys_a.get_override("greet")[0] == "greet", "Function overriden somehow"
    assert greet("World") == "Hello, World!"


def test_expose_module():
    addon, sys_a = create_system("Addon A", {}, "addon_a", ("core",))

    import example_exposed_module

    sys_a.expose_module(example_exposed_module)
    addon.register_system(sys_a)
    del example_exposed_module

    module = client.get_system_module("Addon A", ("core",))
    assert module is not None, "Module not exposed"
    assert hasattr(module, "awesome_function") and hasattr(
        module, "AWESOME_CONSTANT"
    ), "Module exposed incorrectly"
    assert module.AWESOME_CONSTANT == 1, "Module exposed incorrectly"
