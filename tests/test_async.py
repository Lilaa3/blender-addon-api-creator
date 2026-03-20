import asyncio
import inspect
from blender_api_lib.registry import get_registry
from conftest import get_one_hook_validation_error, reg, target
from blender_api_lib.api_types import APIContext


class TestAsyncBasics:
    """Test that a wrapped async function behaves the same as an unwrapped async function."""

    def test_basic_async_call(self, one_addon):
        """A async function with no hooks should behave identically to the original."""
        a, s = one_addon

        @s.function
        async def async_func():
            return "hello"

        reg((a, s))

        async def test():
            result = await async_func()
            assert result == "hello"

            # Control function
            async def control():
                return "hello"

            unwrapped_result = await control()
            assert unwrapped_result == "hello"

        asyncio.run(test())

    def test_async_with_await(self, one_addon):
        """Async function with internal await should work."""
        a, s = one_addon

        @s.function
        async def async_func():
            await asyncio.sleep(1)
            return "done"

        reg((a, s))

        async def test():
            initial_time = asyncio.get_running_loop().time()
            result = await async_func()
            final_time = asyncio.get_running_loop().time()
            assert final_time - initial_time >= 1
            assert result == "done"

        asyncio.run(test())

    def test_async_hook_awaits(self, two_addons):
        """An async hook can perform its own awaits."""
        (a, s), (b, bs) = two_addons
        order = []

        @s.function
        async def main(start_time: float):
            nonlocal order
            assert (asyncio.get_event_loop().time() - start_time) >= 1, "Too fast"
            order.append("main")

        @bs.before(target("main"))
        async def before_hook(start_time: float):
            nonlocal order
            await asyncio.sleep(1)
            order.append("before")

        reg((a, s), (b, bs))

        async def run():
            await main(asyncio.get_event_loop().time())

        asyncio.run(run())
        assert order == ["before", "main"]


class TestAsyncHooks:
    """Test that hooks work correctly with async functions."""

    def test_hooks_basics(self, two_addons):
        (a, s), (b, bs) = two_addons
        order = []

        @s.function
        async def async_func():
            order.append("main_start")
            await asyncio.sleep(0)
            order.append("main_end")
            return "result"

        @bs.before(target("async_func"))
        def before_hook():
            order.append("before")

        @bs.after(target("async_func"))
        def after_hook(ctx: APIContext):
            order.append("after")
            assert ctx.result == "result"

        @bs.after(target("async_func"))
        def after_hook2():
            order.append("after2")

        reg((a, s), (b, bs))

        async def test():
            nonlocal order
            result = await async_func()
            assert result == "result"
            assert order == ["before", "main_start", "main_end", "after", "after2"]

        asyncio.run(test())


class TestAsyncValidation:
    def test_async_hook_on_sync_target(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        def sync_func():
            return 1

        @bs.before(target("sync_func"))
        async def async_hook(ctx: APIContext):
            pass

        reg((a, s), (b, bs))

        assert (
            "cannot attach async hook to sync function"
            in get_one_hook_validation_error()
        )


class TestAsyncTransperancy:
    def test_async_transparency(self, one_addon):
        """Wrapped async functions should still be identified as such by inspect."""
        a, s = one_addon

        @s.function
        async def my_async():
            pass

        reg((a, s))

        assert inspect.iscoroutinefunction(my_async)
        assert not inspect.isgeneratorfunction(my_async)


class TestMixedHooks:
    """Test mixing sync and async hooks on async targets."""

    def test_sync_hook_returning_value_on_async_target(self, two_addons):
        (a, s), (b, bs) = two_addons

        @s.function
        async def async_func():
            return "result"

        @bs.before(target("async_func"))
        def sync_before_hook(ctx: APIContext):
            return 1

        reg((a, s), (b, bs))

        async def run():
            return await async_func()

        asyncio.run(run())
