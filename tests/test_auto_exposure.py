import logging
from blender_api_lib.api_types import RuntimeTargetFunction
from blender_api_lib.registry import get_registry
from conftest import create_system, target, reg, get_target_function


class TestAutoExposure:
    def test_function_auto_name(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function()  # No name provided
        def my_cool_func():
            return "cool"

        reg((a, s_a))

        assert my_cool_func() == "cool"

        # Check if it's in the registry under its own name
        assert get_target_function("my_cool_func", system=("core",))[0] is not None

    def test_hook_auto_exposure(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        order = []

        @s_a.function(name="base")
        def base():
            order.append("base")

        @s_b.hook(target("base"), when="before")
        def hook_of_base():
            order.append("hook")

        # addon A tries to hook into s_b's hook_of_base
        @s_a.hook(RuntimeTargetFunction("Addon B", "hook_of_base", None), when="before")
        def hook_of_hook():
            order.append("hook_of_hook")

        reg((a, s_a), (b, s_b))

        base()
        assert order == ["hook_of_hook", "hook", "base"]

    def test_hook_custom_exposure(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="base")
        def base():
            pass

        @s_b.hook(target("base"), expose_api_as="custom_name")
        def my_hook():
            pass

        reg((a, s_a), (b, s_b))

        r = get_registry()
        sys_b = r._create_runtime_addons()[b.addon_path].systems[s_b.system_name]
        assert "custom_name" in sys_b.functions
        assert "my_hook" not in sys_b.functions

    def test_hook_opt_out_exposure(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="base")
        def base():
            pass

        @s_b.hook(target("base"), expose_api_as=False)
        def private_hook():
            pass

        reg((a, s_a), (b, s_b))

        assert (
            get_target_function("private_hook", addon="Addon B", system=None)[0] is None
        ), "Should not be exposed"

    def test_collision_warning(self, two_addons, caplog):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="collide")
        def func1():
            pass

        # This should trigger a warning because 'collide' is already a function
        @s_a.hook(RuntimeTargetFunction("Other", "base", None), expose_api_as="collide")
        def func2():
            pass

        with caplog.at_level(logging.WARNING):
            reg((a, s_a))

        assert "Collision" in caplog.text
        assert "collide" in caplog.text

    def test_auto_exposed_is_unstable(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="base")
        def base():
            pass

        @s_b.hook(target("base"), when="before")  # auto-exposed
        def hook_of_base():
            pass

        reg((a, s_a), (b, s_b))

        r = get_registry()
        sys_b = r._create_runtime_addons()[b.addon_path].systems[s_b.system_name]
        assert sys_b.functions["hook_of_base"].is_unstable is True
