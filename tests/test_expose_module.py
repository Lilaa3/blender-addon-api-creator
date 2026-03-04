from blender_api_lib import client
from conftest import create_system


class TestExposeModule:
    def test_basic(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))
        import example_exposed_module

        s.expose_module(example_exposed_module)
        a.register_system(s)
        del example_exposed_module

        m = client.get_system_module("Addon A", ("core",))
        assert m is not None, "Module should be exposed"
        assert hasattr(m, "awesome_function"), "Module missing awesome_function"
        assert hasattr(m, "AWESOME_CONSTANT"), "Module missing AWESOME_CONSTANT"
        assert hasattr(m, "AwesomeClass"), "Module missing AwesomeClass"
        assert m.AWESOME_CONSTANT == 1, "AWESOME_CONSTANT should equal 1"
        assert (
            m.awesome_function() == m.AWESOME_CONSTANT
        ), "awesome_function should return constant"
        assert (
            m.AwesomeClass().awesome_method() == m.AWESOME_CONSTANT
        ), "Class method should work"

    def test_returns_none_when_not_exposed(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",), True)
        assert (
            client.get_system_module("Addon A", ("core",)) is None
        ), "Should return None when no module was exposed"
