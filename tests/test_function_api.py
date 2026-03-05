from blender_api_lib.api_types import RuntimeTargetFunction
from conftest import create_system, reg, target


class TestFunctionAPI:
    def test_basic_call(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        @s.function(name="greet")
        def greet(name: str):
            return f"Hello, {name}!"

        a.register_system(s)
        assert s.get_override("greet")[0] == "greet", "Function should be registered"
        assert greet("World") == "Hello, World!", "Function should return correct value"

    def test_return_value(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        @s.function(name="double")
        def double(n):
            return n * 2

        a.register_system(s)
        assert double(7) == 14, "Function should return correct value"

    def test_kwargs(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        @s.function(name="greet")
        def greet(name, greeting):
            return f"{greeting}, {name}!"

        a.register_system(s)
        assert (
            greet("Alice", greeting="Hello") == "Hello, Alice!"
        ), "Should work with kwargs"
        assert greet("Bob", "Hi") == "Hi, Bob!", "Should work with positional args"

    def test_wrapper_preserves_defaults(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        @s.function(name="fn_with_defaults")
        def fn_with_defaults(required, optional_str="hello", optional_int=42):
            return f"{required}-{optional_str}-{optional_int}"

        a.register_system(s)
        assert fn_with_defaults("x") == "x-hello-42", "Wrapper must preserve defaults"
        assert (
            fn_with_defaults("x", "world") == "x-world-42"
        ), "Should override first default"
        assert (
            fn_with_defaults("x", optional_int=0) == "x-hello-0"
        ), "Should override second default"
        assert (
            fn_with_defaults("x", "world", 99) == "x-world-99"
        ), "Should override both"

    def test_call_hook_directly(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        order = []

        @s_a.function(name="base")
        def base():
            order.append("base")

        @s_b.hook(target("base"), when="before")
        def hook_of_base():
            order.append("hook")

        @s_a.hook(RuntimeTargetFunction("Addon B", "hook_of_base", None), when="before")
        def hook_of_hook():
            order.append("hook_of_hook")

        reg((a, s_a), (b, s_b))

        # Call the auto-exposed hook directly.
        hook_of_base()

        assert order == ["hook_of_hook", "hook"]
