from conftest import create_system
import sys
import types


class MockBase:
    @classmethod
    def poll(cls, context):
        return True


class TestClassMethodCollisions:
    def test_expose_all_preserves_classmethod(self):
        class MyPanel(MockBase):
            @classmethod
            def poll(cls, context):
                return "wrapped_poll"

        # Create a mock module
        mod_name = "mock_addon_module"
        mod = types.ModuleType(mod_name)
        mod.__name__ = mod_name
        mod.MyPanel = MyPanel
        sys.modules[mod_name] = mod

        try:
            a, s = create_system("Addon A", {}, "addon_a", ("core",))

            s.expose_all(mod, recursive=True)

            # Check if MyPanel.poll is still a classmethod
            descriptor = MyPanel.__dict__.get("poll")
            assert isinstance(
                descriptor, classmethod
            ), f"Expected classmethod, got {type(descriptor)}"

            assert MyPanel.poll(None) == "wrapped_poll"

        finally:
            del sys.modules[mod_name]

    def test_expose_all_does_not_shadow_inherited_classmethod(self):
        mod_name = "mock_addon_module_inherited"
        mod = types.ModuleType(mod_name)
        mod.__name__ = mod_name
        sys.modules[mod_name] = mod

        try:

            class MyPanel(MockBase):
                pass

            MyPanel.__module__ = mod_name
            mod.MyPanel = MyPanel

            a, s = create_system("Addon A", {}, "addon_a", ("core",))
            s.expose_all(mod, recursive=True)

            assert (
                "poll" not in MyPanel.__dict__
            ), "expose_all should not wrap inherited members"

            # Verify it still works as a classmethod
            assert MyPanel.poll(None) is True

        finally:
            del sys.modules[mod_name]
