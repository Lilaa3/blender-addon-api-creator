import inspect
import pytest
from conftest import get_one_hook_validation_error, reg, target, V
from blender_api_lib.api_types import APIContext
from blender_api_lib.registry import get_registry


class TestGeneratorBasics:
    """Test that a wrapped generator behaves behaves the same as an an unwrapped generator."""

    def test_yield_with_return_value(self, one_addon):
        """Return value of generator should be preserved."""
        a, s = one_addon

        @s.function
        def gen():
            yield 1
            return "done"

        reg((a, s))

        def run_and_get_return(gen_func):
            g = gen_func()
            results = []
            while True:
                try:
                    results.append(next(g))
                except StopIteration as e:
                    return results, e.value

        wrapped_results, wrapped_return = run_and_get_return(gen)
        assert wrapped_results == [1]
        assert wrapped_return == "done"

    def test_send_method(self, one_addon):
        """The .send() method should work identically."""
        a, s = one_addon

        @s.function
        def gen():
            received = yield "ready"
            yield received

        reg((a, s))

        g = gen()
        assert next(g) == "ready"
        assert g.send("hello") == "hello"

    def test_throw_method(self, one_addon):
        """The .throw() method should work."""
        a, s = one_addon

        @s.function
        def gen():
            try:
                yield 1
            except ValueError:
                yield "caught"
            yield 2

        reg((a, s))

        g = gen()
        assert next(g) == 1
        assert g.throw(ValueError) == "caught"
        assert next(g) == 2

    def test_close_method(self, one_addon):
        """The .close() method should work."""
        a, s = one_addon

        closed = []

        @s.function
        def gen():
            try:
                yield 1
            finally:
                closed.append(True)
            yield 2

        reg((a, s))

        g = gen()
        next(g)
        g.close()
        assert closed == [True]


class TestGeneratorHooks:
    """Test that hooks work correctly with generators."""

    def test_before_hook_runs_at_iteration_start(self, two_addons):
        """Before hook should run when iteration starts."""
        (a, s), (b, bs) = two_addons
        order = []

        @s.function
        def gen():
            order.append("gen")
            yield 1

        @bs.before(target("gen"))
        def before_hook(ctx: APIContext):
            order.append("before")

        reg((a, s), (b, bs))

        g = gen()
        assert order == []
        next(g)
        assert order == ["before", "gen"]
        list(g)
        assert order == ["before", "gen"]

    def test_before_hook_yielding(self, two_addons):
        """Before hook that yields should pause execution and yield out."""
        (a, s), (b, bs) = two_addons
        order = []

        @s.function
        def gen():
            order.append("gen")
            yield "main_yield"

        @bs.before(target("gen"))
        def before_hook(ctx: APIContext):
            order.append("before")
            yield "hook_yield"

        @bs.after(target("gen"))
        def after_hook(ctx: APIContext):
            yield "after_yield"
            order.append("after")

        reg((a, s), (b, bs))

        g = gen()
        assert order == []

        res1 = next(g)
        assert res1 == "hook_yield"
        assert order == ["before"]

        res2 = next(g)
        assert res2 == "main_yield"
        assert order == ["before", "gen"]

        res_list = list(g)
        assert res_list == ["after_yield"]
        assert order == ["before", "gen", "after"]

    def test_after_hook_can_read_yields(self, two_addons):
        """After hook should be able to read the inner generator via ctx."""
        (a, s), (b, bs) = two_addons

        @s.function
        def gen():
            yield 1
            yield 2

        generator_from_hook = []

        @bs.after(target("gen"))
        def after_hook(ctx: APIContext):
            generator_from_hook.append(ctx.original_generator)

        reg((a, s), (b, bs))

        g = gen()
        res = list(g)
        assert res == [1, 2]

        assert len(generator_from_hook) == 1
        raw_gen = generator_from_hook[0]
        assert list(raw_gen) == []

    def test_after_hook_replace_mode(self, two_addons):
        """After hook replace mode can grab the original generator and replace."""
        (a, s), (b, bs) = two_addons

        @s.function
        def gen():
            yield 1
            yield 2
            yield 3
            return "final_value"

        @bs.after(target("gen"), generator_mode="intercept")
        def replace_hook(ctx: APIContext):
            original = ctx.original_generator
            assert original is not None

            first_val = next(original)
            yield first_val * 10

            for val in original:
                yield val * 100

            return ctx.result + "_intercepted"

        reg((a, s), (b, bs))

        g = gen()
        while True:
            try:
                next(g)
            except StopIteration as e:
                assert e.value == "final_value_intercepted"
                break

    def test_generator_attributes_preserved(self, one_addon):
        """Wrapped generators should still be real generators with expected attributes."""
        (a, s) = one_addon

        @s.function
        def gen():
            yield 1

        reg((a, s))

        g = gen()
        assert inspect.isgenerator(g)
        next(g)
        assert inspect.getgeneratorstate(g) == inspect.GEN_SUSPENDED
        list(g)
        assert inspect.getgeneratorstate(g) == inspect.GEN_CLOSED

    def test_multiple_intercept_hooks(self, two_addons):
        """Test that multiple intercept hooks can coexist without colliding on original_generator."""
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="gen")
        def gen():
            yield 1
            yield 2

        @s_b.after(target("gen"), generator_mode="intercept")
        def hook1(ctx: APIContext):
            orig = ctx.original_generator
            assert orig is not None
            for val in orig:
                yield val * 10

        @s_b.after(target("gen"), generator_mode="intercept")
        def hook2(ctx: APIContext):
            orig = ctx.original_generator
            assert orig is not None
            for val in orig:
                yield val * 100

        reg((a, s_a), (b, s_b))

        assert list(gen()) == [1000, 2000]

    def test_generator_override_exception_tracking(self, two_addons):
        """Test that exceptions in overridden generators are correctly attributed"""

        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="gen", version=V(1, 0, 0))
        def gen():
            yield 1

        @s_b.override(target("gen"))
        def over_gen():
            yield 1
            raise ValueError("override error")

        @s_b.before(target("gen"))
        def before_hook():
            yield 2

        reg((a, s_a), (b, s_b))

        it = gen()
        assert next(it) == 2

        with pytest.raises(RuntimeError) as excinfo:
            list(gen())

        assert (
            "Exception in active function over_gen of Addon B: override error"
            in str(excinfo.value)
        )


class TestGeneratorValidation:
    def test_generator_hook_on_non_generator(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        def sync_func():
            return 1

        @bs.before(target("sync_func"))
        def gen_hook(ctx: APIContext):
            yield 1

        reg((a, s), (b, bs))

        assert (
            "cannot attach a generator hook to a non-generator function"
            in get_one_hook_validation_error()
        )

    def test_intercept_hook_must_be_generator(self, two_addons):
        """_get_hook_validation_error should catch non-generator intercept hooks at registration time."""
        (a, s), (b, bs) = two_addons

        @s.function
        def gen():
            yield 1

        @bs.after(target("gen"), generator_mode="intercept")
        def non_gen_hook(ctx: APIContext):
            return 1

        reg((a, s), (b, bs))

        assert (
            "intercept hook must be a sync generator" in get_one_hook_validation_error()
        )

    def test_generator_transparency(self, one_addon):
        """Wrapped generators should still be identified as such by inspect."""
        a, s = one_addon

        @s.function
        def my_gen():
            yield 1

        reg((a, s))

        assert inspect.isgeneratorfunction(my_gen)
        assert not inspect.iscoroutinefunction(my_gen)
