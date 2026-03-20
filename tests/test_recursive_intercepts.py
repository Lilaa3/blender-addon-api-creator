import pytest
import asyncio
from typing import Generator, AsyncGenerator
from blender_api_lib.api_types import APIContext, RuntimeTargetFunction
from conftest import reg, target


def test_sync_before_hook_intercepted(two_addons):
    """
    Tests that an intercept hook applied to a generator correctly wraps
    the ENTIRE inner execution, meaning the intercept hook will receive
    items yielded by the BEFORE hooks as well!
    """
    (a, s), (b, bs) = two_addons

    @s.function
    def main_gen():
        yield "main_1"
        yield "main_2"

    @bs.before(target("main_gen"))
    def before_hook_gen(ctx: APIContext):
        yield "before_1"
        yield "before_2"

    @bs.after(target("main_gen"), generator_mode="intercept")
    def intercept_hook(ctx: APIContext):
        orig = ctx.original_generator
        assert orig is not None
        # Intercepts the ENTIRE stream (before + main)
        for val in orig:
            yield f"intercepted_{val}"

    reg((a, s), (b, bs))

    res = list(main_gen())
    assert res == [
        "intercepted_before_1",
        "intercepted_before_2",
        "intercepted_main_1",
        "intercepted_main_2",
    ]


def test_intercept_only_before_hook(two_addons):
    """
    Tests that targeting a hook explicitly allows replacing ONLY that hook.
    """
    (a, s), (b, bs) = two_addons

    @s.function
    def main_gen():
        yield "main"

    @bs.before(target("main_gen"), expose_api_as="my_before_api")
    def before_hook(ctx: APIContext):
        yield "before"

    @s.after(
        RuntimeTargetFunction("Addon B", "my_before_api", None),
        generator_mode="intercept",
    )
    def intercept_hook(ctx: APIContext):
        orig = ctx.original_generator
        assert orig is not None
        # Replace completely: don't yield from orig!
        yield "intercepted"

    reg((a, s), (b, bs))

    res = list(main_gen())
    # "before" should be replaced by "intercepted"
    # "main" should remain as-is
    assert res == ["intercepted", "main"]


@pytest.mark.asyncio
async def test_async_intercept_only_before_hook(two_addons):
    (a, s), (b, bs) = two_addons

    @s.function
    async def main_gen():
        yield "main"

    @bs.before(target("main_gen"), expose_api_as="my_before_api_async")
    async def before_hook(ctx: APIContext):
        yield "before"

    @s.after(
        RuntimeTargetFunction("Addon B", "my_before_api_async", None),
        generator_mode="intercept",
    )
    async def intercept_hook(ctx: APIContext):
        orig = ctx.original_generator
        assert orig is not None
        yield "intercepted_async"

    reg((a, s), (b, bs))

    res = []
    async for v in main_gen():
        res.append(v)
    assert res == ["intercepted_async", "main"]


@pytest.mark.asyncio
async def test_async_before_hook_intercepted(two_addons):
    (a, s), (b, bs) = two_addons

    @s.function
    async def main_gen():
        yield "main_1"
        yield "main_2"

    @bs.before(target("main_gen"))
    async def before_hook_gen(ctx: APIContext):
        yield "before_1"
        yield "before_2"

    @bs.after(target("main_gen"), generator_mode="intercept")
    async def intercept_hook(ctx: APIContext):
        orig = ctx.original_generator
        assert orig is not None
        async for val in orig:
            yield f"intercepted_{val}"

    reg((a, s), (b, bs))

    res = []
    async for v in main_gen():
        res.append(v)

    assert res == [
        "intercepted_before_1",
        "intercepted_before_2",
        "intercepted_main_1",
        "intercepted_main_2",
    ]
