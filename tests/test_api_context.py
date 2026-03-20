from blender_api_lib.api_types import APIContext


# TODO: test hook interactions
class TestAPIContext:
    def test_set_and_get(self):
        ctx = APIContext(api_name="test", calling_addon="addon_a", args=[], kwargs={})
        ctx.set_data("key", 42)
        assert ctx.get_data("key") == 42

    def test_get_missing_key(self):
        ctx = APIContext(api_name="test", calling_addon="addon_a", args=[], kwargs={})
        assert ctx.get_data("nonexistent") is None

    def test_get_args_missing(self):
        ctx = APIContext(
            api_name="test",
            calling_addon="addon_a",
            args=[],
            kwargs={},
            arguments={"x": 5},
        )
        result = ctx.get_args("x", "y")
        assert len(result) == 2, "Should return all args"
        assert result[0] == 5, "X should be 5"
        assert result[1] is None, "Missing argument should come back as None"

    def test_overwrite_value(self):
        ctx = APIContext(api_name="test", calling_addon="addon_a", args=[], kwargs={})
        ctx.set_data("k", 1)
        ctx.set_data("k", 2)
        assert ctx.get_data("k") == 2, "Later set_data should overwrite earlier value"

    def test_accepts_any_type(self):
        ctx = APIContext(api_name="test", calling_addon="addon_a", args=[], kwargs={})
        ctx.set_data("list", [1, 2, 3])
        ctx.set_data("none", None)
        ctx.set_data("dict", {"a": 1})
        assert ctx.get_data("list") == [1, 2, 3]
        assert ctx.get_data("none") is None
        assert ctx.get_data("dict") == {"a": 1}

    def test_context_copy_shares_store(self):
        ctx = APIContext(
            api_name="test",
            calling_addon="addon",
            args=[],
            kwargs={},
            _store={"shared": True},
        )
        ctx.active_addon = "old"

        ctx2 = ctx.copy()
        assert ctx2.api_name == ctx.api_name
        assert ctx2.active_addon == "old"
        assert ctx2.get_data("shared") is True

        # Modify store in copy
        ctx2.set_data("new", 1)
        assert ctx.get_data("new") == 1, "Original should be modified"

        # Modify attribute in copy
        ctx2.active_addon = "new"
        assert ctx.active_addon == "old", "Original should not be modified"
