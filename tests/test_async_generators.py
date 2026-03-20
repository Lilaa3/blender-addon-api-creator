import asyncio
import inspect
from blender_api_lib.registry import get_registry
from conftest import get_one_hook_validation_error, reg, target
from blender_api_lib.api_types import APIContext


class TestAsyncGenerators:
    def test_basic_async_generator(self, one_addon):
        a, s = one_addon

        @s.function
        async def async_gen():
            yield 1
            await asyncio.sleep(0.01)
            yield 2

        reg((a, s))

        async def test():
            results = []
            async for val in async_gen():
                results.append(val)
            assert results == [1, 2]

        asyncio.run(test())

    def test_async_generator_with_hooks(self, two_addons):
        (a, s), (b, bs) = two_addons
        order = []

        @s.function
        async def async_gen():
            nonlocal order
            order.append("gen_start")
            yield 1
            await asyncio.sleep(0.01)
            yield 2
            order.append("gen_end")

        @bs.before(target("async_gen"))
        async def before_hook():
            nonlocal order
            order.append("before")

        @bs.after(target("async_gen"))
        async def after_hook(ctx: APIContext):
            nonlocal order
            order.append("after")
            yield 3

        reg((a, s), (b, bs))

        async def test():
            nonlocal order
            results = []
            g = async_gen()
            async for val in g:
                results.append(val)

            assert results == [1, 2, 3]
            assert order == ["before", "gen_start", "gen_end", "after"]

            # run a second time
            order = []
            results = []
            g = async_gen()
            async for val in g:
                results.append(val)

            assert results == [1, 2, 3]
            assert order == ["before", "gen_start", "gen_end", "after"]

        asyncio.run(test())


class TestAsyncGeneratorAthrow:
    def test_athrow_propagation(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function()
        async def agen():
            try:
                yield 1
            except ValueError as e:
                yield str(e)
            yield 2

        @bs.before(target("agen"))
        async def hook(ctx: APIContext):
            pass

        reg((a, s), (b, bs))

        async def run():
            g = agen()
            v1 = await g.asend(None)
            assert v1 == 1
            v2 = await g.athrow(ValueError("injected"))
            assert v2 == "injected"
            v3 = await g.asend(None)
            assert v3 == 2

        asyncio.run(run())

    def test_aclose_propagation(self, one_addon):
        a, s = one_addon
        closed = []

        @s.function()
        async def agen():
            try:
                yield 1
            finally:
                closed.append(True)

        reg((a, s))

        async def run():
            g = agen()
            await g.asend(None)
            await g.aclose()
            assert closed == [True]

        asyncio.run(run())

    def test_asend_fast_path(self, one_addon):
        a, s = one_addon

        @s.function
        async def async_gen():
            val = yield 1
            yield val

        reg((a, s))

        async def test():
            gen = async_gen()
            v1 = await gen.asend(None)
            assert v1 == 1
            v2 = await gen.asend(42)
            assert v2 == 42
            try:
                await gen.asend(None)
            except StopAsyncIteration:
                pass

        asyncio.run(test())

    def test_asend_with_hooks(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            val = yield 1
            yield val

        @bs.before(target("async_gen"))
        async def before_hook(ctx: APIContext):
            pass

        reg((a, s), (b, bs))

        async def test():
            gen = async_gen()
            v1 = await gen.asend(None)
            assert v1 == 1
            v2 = await gen.asend(42)
            assert v2 == 42
            try:
                await gen.asend(None)
            except StopAsyncIteration:
                pass

        asyncio.run(test())


class TestAsyncGeneratorIntercept:
    def test_intercept_mode(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            yield 1
            yield 2

        @bs.after(target("async_gen"), generator_mode="intercept")
        async def intercept_hook(ctx: APIContext):
            original = ctx.original_generator
            assert original is not None
            async for val in original:
                yield val * 10

        reg((a, s), (b, bs))

        async def test():
            results = []
            async for val in async_gen():
                results.append(val)
            assert results == [10, 20]

        asyncio.run(test())

    def test_with_asend(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            val = yield 1
            yield val + 1

        @bs.after(target("async_gen"), generator_mode="intercept")
        async def intercept_hook(ctx: APIContext):
            original = ctx.original_generator
            assert original is not None
            v1 = await original.asend(None)
            sent = yield v1 * 10
            v2 = await original.asend(sent)
            yield v2 * 100

        reg((a, s), (b, bs))

        async def test():
            g = async_gen()
            v1 = await g.asend(None)
            assert v1 == 10
            v2 = await g.asend(5)
            assert v2 == 600  # (5 + 1) * 100

        asyncio.run(test())


class TestAsyncGeneratorValidation:
    def test_async_gen_hook_on_sync_gen_target(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        def sync_gen():
            yield 1

        @bs.before(target("sync_gen"))
        async def async_gen_hook(ctx: APIContext):
            yield 1

        reg((a, s), (b, bs))

        assert (
            "cannot attach async generator hook to sync generator function"
            in get_one_hook_validation_error()
        )

    def test_async_hook_on_sync_gen_target(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        def sync_gen():
            yield 1

        @bs.before(target("sync_gen"))
        async def async_hook(ctx: APIContext):
            pass

        reg((a, s), (b, bs))

        assert (
            "cannot attach async hook to sync generator function"
            in get_one_hook_validation_error()
        )

    def test_sync_gen_intercepting_async_stream(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            yield 1

        @bs.after(target("async_gen"), generator_mode="intercept")
        def sync_gen_hook(ctx: APIContext):
            yield 1

        reg((a, s), (b, bs))

        assert (
            "sync generator intercept hook cannot attach to async generator"
        ) in get_one_hook_validation_error()

    def test_intercept_hook_must_be_async_generator(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            yield 1

        @bs.after(target("async_gen"), generator_mode="intercept")
        async def non_gen_hook(ctx: APIContext):
            return 1

        reg((a, s), (b, bs))

        assert (
            "intercept hook must be an async generator"
            in get_one_hook_validation_error()
        )


class TestAsyncGeneratorTransparency:
    def test_async_generator_transparency(self, one_addon):
        """Wrapped async generators should still be identified as such by inspect."""
        a, s = one_addon

        @s.function
        async def my_async_gen():
            yield 1

        reg((a, s))

        assert inspect.isasyncgenfunction(my_async_gen)
        assert not inspect.iscoroutinefunction(my_async_gen)
        assert not inspect.isgeneratorfunction(my_async_gen)


class TestMixedGeneratorHooks:
    """Test mixing sync and async hooks on async targets."""

    def test_sync_gen_hook_on_async_gen_target(self, two_addons):
        """Sync generator hooks should work on async generators (not as intercept)"""
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_gen():
            yield 2

        @bs.before(target("async_gen"))
        def sync_gen_hook(ctx: APIContext):
            yield 1

        @bs.after(target("async_gen"))
        def sync_after_hook(ctx: APIContext):
            yield 3

        reg((a, s), (b, bs))

        async def run():
            res = []
            async for v in async_gen():
                res.append(v)
            return res

        assert asyncio.run(run()) == [1, 2, 3]
