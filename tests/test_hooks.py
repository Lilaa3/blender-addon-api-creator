from blender_api_lib.api_types import (
    APIContext,
    RuntimeExposedHook,
    RuntimeTargetFunction,
)
from conftest import V, create_system, target, reg


class TestHooks:
    def test_before_runs_before(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        order = []

        @s_a.function(name="work")
        def work():
            order.append("main")

        @s_b.hook(target("work"), when="before")
        def before_work():
            order.append("before")

        reg((a, s_a), (b, s_b))
        work()
        assert order == ["before", "main"], "Before hook must run before main"

    def test_after_preserves_return(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="val")
        def val():
            return 99

        @s_b.hook(target("val"), when="after")
        def after_val():
            return None

        reg((a, s_a), (b, s_b))
        assert val() == 99, "After hook returning None must not clobber main's return"

    def test_after_runs_after(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        order = []

        @s_a.function(name="work")
        def work():
            order.append("main")

        @s_b.hook(target("work"), when="after")
        def after_work():
            order.append("after")

        reg((a, s_a), (b, s_b))
        work()
        assert order == ["main", "after"], "After hook must run after main"

    def test_before_and_after_order(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        order = []

        @s_a.function(name="work")
        def work():
            order.append("main")

        @s_b.hook(target("work"), when="before")
        def before_work():
            order.append("before")

        @s_b.hook(target("work"), when="after")
        def after_work():
            order.append("after")

        reg((a, s_a), (b, s_b))
        work()
        assert order == ["before", "main", "after"], f"Order was {order}"

    def test_hook_receives_args(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        received = []

        @s_a.function(name="add")
        def add(x, y):
            return x + y

        @s_b.hook(target("add"), when="before")
        def before_add(x, y):
            received.append((x, y))

        reg((a, s_a), (b, s_b))
        assert add(3, 4) == 7, "Function should return correct value"
        assert received == [(3, 4)], "Hook should receive the same args as main"

    def test_hook_with_ctx(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        captured = []

        @s_a.function(name="ping")
        def ping():
            return "pong"

        @s_b.hook(target("ping"), when="before")
        def before_ping(ctx: APIContext):
            captured.append(ctx)

        reg((a, s_a), (b, s_b))
        ping()
        assert len(captured) == 1, "Hook should have been called"
        assert isinstance(captured[0], APIContext), "Hook should receive APIContext"
        assert captured[0].api_name == "ping", "Context should have correct api_name"

    def test_ctx_shared_between_hooks(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        c, s_c = create_system("Addon C", {}, "addon_c", None)
        observed = []

        @s_a.function(name="process")
        def process():
            pass

        @s_b.hook(target("process"), when="before")
        def before_process(ctx: APIContext):
            ctx.set_data("token", "hello")

        @s_c.hook(target("process"), when="after")
        def after_process(ctx: APIContext):
            observed.append(ctx.get_data("token"))

        reg((a, s_a), (b, s_b), (c, s_c))
        process()
        assert observed == [
            "hello"
        ], "After hook should see value written by before hook"

    def test_ctx_is_main_false_in_hooks(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        values = []

        @s_a.function(name="doit")
        def doit():
            pass

        @s_b.hook(target("doit"), when="before")
        def before_doit(ctx: APIContext):
            values.append(("before", ctx.is_main))

        @s_b.hook(target("doit"), when="after")
        def after_doit(ctx: APIContext):
            values.append(("after", ctx.is_main))

        reg((a, s_a), (b, s_b))
        doit()
        assert ("before", False) in values, "Before hook should not be main"
        assert ("after", False) in values, "After hook should not be main"

    def test_ctx_active_fields(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", ("ext",))
        snapshots = []

        @s_a.function(name="target_fn")
        def target_fn():
            pass

        @s_b.hook(target("target_fn"), when="before")
        def b_before(ctx: APIContext):
            snapshots.append((ctx.active_addon, ctx.active_system, ctx.active_function))

        reg((a, s_a), (b, s_b))
        target_fn()
        active_addon, active_system, active_function = snapshots[0]
        assert active_addon == "Addon B", "active_addon should be the hook's addon"
        assert (
            active_function == "b_before"
        ), "active_function should be the hook function name"

    def test_ctx_calling_addon_reflects_owner(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        captured = []

        @s_a.function(name="owned_fn")
        def owned_fn():
            pass

        @s_b.hook(target("owned_fn"), when="before")
        def b_hook(ctx: APIContext):
            captured.append(ctx.calling_addon)

        reg((a, s_a), (b, s_b))
        owned_fn()
        assert captured == ["addon_a"], "calling_addon should be the API owner's path"

    def test_get_args_by_name(self, two_addons):
        (a, s_a), (b, s_b) = two_addons
        extracted = []

        @s_a.function(name="named")
        def named(alpha, beta):
            return alpha + beta

        @s_b.hook(target("named"), when="before")
        def before_named(ctx: APIContext):
            extracted.append(ctx.get_args("alpha", "beta"))

        reg((a, s_a), (b, s_b))
        named(10, 20)
        assert extracted == [(10, 20)], "get_args should resolve by parameter name"

    def test_complex_chaining(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", ("ext",))
        c, s_c = create_system("Addon C", {}, "addon_c", None)
        d, s_d = create_system("Addon D", {}, "addon_d", None)
        order = []

        @s_a.function(name="base_fn", version=V(1, 0, 0))
        def base_fn():
            order.append("original")
            return "original"

        @s_b.override(
            target("base_fn"),
            expose_api_as=RuntimeExposedHook(name="b_override"),
        )
        def b_override():
            order.append("b_override")
            return "b_override"

        @s_c.hook(
            RuntimeTargetFunction("Addon B", "b_override", ("ext",)), when="before"
        )
        def b_before():
            order.append("b_before")

        # test if can still target replaced function
        @s_c.hook(
            target("base_fn"),
            when="before",
            expose_api_as=RuntimeExposedHook(name="a_before"),
        )
        def a_before():
            order.append("a_before")

        @s_d.hook(RuntimeTargetFunction("Addon C", "a_before"), when="after")
        def a_after():
            order.append("a_before_after")

        reg((a, s_a), (b, s_b), (c, s_c), (d, s_d))

        result = base_fn()

        assert result == "b_override", "Override should be active"
        print(order)
        assert order == [
            "a_before",
            "a_before_after",
            "b_before",
            "b_override",
        ], "Hooks should run in correct order"
