import sys
import pytest

from blender_api_lib import client, registry
from blender_api_lib.api_types import (
    APIVersion,
    RuntimeTargetAddon,
    RuntimeTargetFunction,
    SystemKey,
)


@pytest.fixture(autouse=True)
def clean_registry():
    _tracked_addons.clear()
    client.API_ADDON_SINGLETON = None
    client.SYSTEMS.clear()

    if registry._GLOBAL_KEY in sys.modules:
        del sys.modules[registry._GLOBAL_KEY]

    registry.register_registry(reload=True, with_ui=False)

    yield

    for addon in _tracked_addons:
        for system in addon.systems.values():
            system._restore_expose_all_originals()

    _tracked_addons.clear()
    client.API_ADDON_SINGLETON = None
    client.SYSTEMS.clear()
    if registry._GLOBAL_KEY in sys.modules:
        del sys.modules[registry._GLOBAL_KEY]


_tracked_addons: list = []


def create_addon(name: str, bl_info: dict, addon_path: str, register: bool = True):
    addon = client.APIAddon(name=name, bl_info=bl_info, addon_path=addon_path)
    _tracked_addons.append(addon)
    if register:
        addon.register_addon()
    return addon


def create_system(
    name: str,
    bl_info: dict,
    addon_path: str,
    system_name: SystemKey,
    register: bool = False,
):
    addon = create_addon(name=name, bl_info=bl_info, addon_path=addon_path)
    sys = client.APISystem(system_name=system_name, _addon_path=addon_path)
    if register:
        addon.register_system(sys)
    return addon, sys


def reg(*pairs):
    """Register each (addon, system) pair. Eliminates the repeated two-line register block."""
    for addon, system in pairs:
        addon.register_system(system)


def V(major, minor=0, patch=0) -> APIVersion:
    """Shorthand for APIVersion(major, minor, patch)."""
    return APIVersion(major, minor, patch)


@pytest.fixture
def two_addons():
    """Returns ((addon, sys_a), (addon_b, sys_b)) — the most common two-addon test setup."""
    pair_a = create_system("Addon A", {}, "addon_a", ("core",))
    pair_b = create_system("Addon B", {}, "addon_b", None)
    return pair_a, pair_b


def core_target(fn_name: str) -> RuntimeTargetFunction:
    """Shorthand for RuntimeTargetFunction('Addon A', fn_name, ('core',))."""
    return RuntimeTargetFunction("Addon A", fn_name, ("core",))


def core_target_addon(system=("core",)) -> RuntimeTargetAddon:
    """Shorthand for RuntimeTargetAddon('Addon A', system)."""
    return RuntimeTargetAddon("Addon A", system)


def get_target_function(func: str, addon: str = "Addon A", system: SystemKey = None):
    return registry.get_registry()._get_target_function(
        RuntimeTargetFunction(addon, func, system)
    )


def assert_if_function_exposed(
    func: str, addon: str = "Addon A", system: SystemKey = None, expected: bool = True
):
    result = get_target_function(func, addon, system)
    assert (
        result[0] is not None
    ) == expected, f"Function {func} should {'not ' if not expected else ''}be exposed. {result[1]}"
    return result


def target(fn: str, system: SystemKey = ("core",)) -> RuntimeTargetFunction:
    """Shorthand for RuntimeTargetFunction('Addon A', fn, system)."""
    return RuntimeTargetFunction("Addon A", fn, system)


def assert_exposed(func: str, system: SystemKey = None):
    """Assert function is exposed, with clean error message."""
    result = get_target_function(func, "Addon A", system)
    assert result[0], f"{func} should be exposed: {result[1]}"


def assert_not_exposed(func: str, system: SystemKey = None):
    """Assert function is NOT exposed, with clean error message."""
    result = get_target_function(func, "Addon A", system)
    assert not result[0], f"{func} should not be exposed: {result[1]}"
