from blender_api_lib import registry
from blender_api_lib.api_types import RuntimeTargetFunction
from conftest import (
    create_system,
    assert_if_function_exposed,
    assert_exposed,
    assert_not_exposed,
)


class MyService:
    def public_method(self):
        return "pub"

    def _private_method(self):
        return "pub"


class TestExposeAll:
    def test_only_public(self):
        a, s = create_system("Addon A", {}, "addon_a", None)
        s.expose_all(MyService)
        a.register_system(s)

        assert_exposed("public_method")
        assert_not_exposed("_private_method")

    def test_include_private(self):
        a, s = create_system("Addon A", {}, "addon_a", None)
        s.expose_all(MyService, hide_private=False)
        a.register_system(s)

        assert_exposed("public_method")
        assert_exposed("_private_method")

    def test_no_double_wrap(self):
        a, s = create_system("Addon A", {}, "addon_a", ("core",))

        class MyWrappedService:
            @s.function(name="wrapped_method")
            def wrapped_method(self):
                return "pub"

            def public_method(self):
                return "pub"

        original_wrapped = id(MyWrappedService.wrapped_method)
        original_public = id(MyWrappedService.public_method)
        s.expose_all(MyWrappedService)
        a.register_system(s)

        assert id(MyWrappedService.wrapped_method) == original_wrapped
        assert id(MyWrappedService.public_method) != original_public

    def test_unregister(self):
        a, s = create_system("Addon A", {}, "addon_a", None)
        s.expose_all(MyService)
        a.register_system(s)
        assert_exposed("public_method")

        a.unregister_addon()
        assert_not_exposed("public_method")

        a, s = create_system("Addon A", {}, "addon_a", None)
        s.expose_all(MyService)
        a.register_system(s)
        assert_exposed("public_method")

    def test_prefix(self):
        import example_expose_all

        a, s = create_system("Addon A", {}, "addon_a", None)
        s.expose_all(example_expose_all, starting_prefix="prefix.", hide_private=False)
        a.register_system(s)

        assert_exposed("prefix.cool_function")
        assert_exposed("prefix.CoolClass.__init__")
        assert_exposed("prefix.CoolClass.cool_function")

    def test_wildcarding(self):
        import example_wildcarding

        total = (
            "name_prefix",
            "name_suffix",
            "prefix_name",
            "safe_name",
            "suffix_name",
        )
        expected = {
            ("*_prefix",): ("name_suffix", "prefix_name", "safe_name", "suffix_name"),
            ("*prefix*",): ("name_suffix", "safe_name", "suffix_name"),
            ("*suffix*",): ("name_prefix", "prefix_name", "safe_name"),
            ("*suffix", "*_suffix"): (
                "name_prefix",
                "prefix_name",
                "safe_name",
                "suffix_name",
            ),
            ("prefix*", "prefix_*"): (
                "name_prefix",
                "name_suffix",
                "safe_name",
                "suffix_name",
            ),
            ("prefix", "suffix"): (
                "name_prefix",
                "name_suffix",
                "prefix_name",
                "safe_name",
                "suffix_name",
            ),
            ("suffix_*",): ("name_prefix", "name_suffix", "prefix_name", "safe_name"),
        }

        for wildcards, attrs in expected.items():
            for wildcard in wildcards:
                a, s = create_system("Addon A", {}, "addon_a", None)
                s.expose_all(example_wildcarding, exclude=[wildcard])
                a.register_system(s)

                for attr in attrs:
                    assert_exposed(attr), f"{attr} should be exposed for {wildcard}"
                for attr in (x for x in total if x not in attrs):
                    assert_not_exposed(
                        attr
                    ), f"{attr} should not be exposed for {wildcard}"

                a.unregister_addon()
