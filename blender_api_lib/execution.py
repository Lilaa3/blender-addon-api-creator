import inspect
from typing import Any, Callable, Optional
from .api_types import APIContext, ExecutionChainStep, ExecutionStep


def flatten_execution_chain(chain: ExecutionChainStep, is_root=True):
    """Recursively fully flattens an execution chain into an ordered list of execution node tuples."""
    nodes = []
    for old in chain.old_main:
        for b in old.before:
            nodes.extend(flatten_execution_chain(b, False))
    for b in chain.before:
        nodes.extend(flatten_execution_chain(b, False))
    nodes.append((chain.main, is_root))
    for a in chain.after:
        nodes.extend(flatten_execution_chain(a, False))
    for old in reversed(chain.old_main):
        for a in old.after:
            nodes.extend(flatten_execution_chain(a, False))
    return nodes


def get_func_traits(func: Callable):
    """Detect if a function is async, a generator, or an async generator."""
    is_async_gen = inspect.isasyncgenfunction(func)
    is_async = inspect.iscoroutinefunction(func) or is_async_gen
    is_gen = inspect.isgeneratorfunction(func) or is_async_gen
    return is_async, is_gen, is_async_gen


def _normalize_gen(gen):
    """Bridges sync generators to an async-compatible interface with asend/athrow/aclose."""
    if hasattr(gen, "asend"):
        return gen

    class _Adapter:
        def __init__(self, g):
            self.g = g

        async def asend(self, v):
            try:
                return self.g.send(v) if v is not None else next(self.g)
            except StopIteration as e:
                raise StopAsyncIteration from e

        async def athrow(self, e):
            try:
                return self.g.throw(e)
            except StopIteration as e:
                raise StopAsyncIteration from e

        async def aclose(self):
            self.g.close()

    return _Adapter(gen)


def get_ctx_mode(func: Callable):
    """Determine if a function expects the APIContext 'ctx' as its only parameter."""
    try:
        sig = inspect.signature(func)
    except ValueError:
        return False
    params = list(sig.parameters.values())
    if len(params) != 1:
        return False
    p = params[0]
    return p.name == "ctx" and (
        p.annotation is APIContext
        or p.annotation == "APIContext"
        or getattr(p.annotation, "__name__", None) == "APIContext"
    )


def call_with_context(
    mode: bool, func: Callable, ctx: APIContext, args: list[Any], kwargs: dict[str, Any]
):
    """Dispatch function call using either the context object or raw args/kwargs."""
    return func(ctx) if mode else func(*args, **kwargs)


def _setup_step(ctx: APIContext, step: ExecutionStep):
    """Create a new context configured for a specific execution step."""
    new_ctx = ctx.copy()
    new_ctx.active_addon = step.addon_name
    new_ctx.active_system = step.system_name
    new_ctx.active_function = step.name
    new_ctx.is_main = step.is_main
    new_ctx.active_hash = step.step_hash
    new_ctx.target_hash = new_ctx.unstable_hashes.get(step.name)
    return step.func, step.ctx_mode, new_ctx


def _handle_exc(e: Exception, ctx: APIContext, f: Callable, orig: Callable):
    """Wrap exceptions from hooks with detailed context metadata."""
    if f is orig:
        raise e
    phase = "active" if ctx.is_main else "hook"
    raise RuntimeError(
        f"Exception in {phase} function {ctx.active_function} of {ctx.active_addon}: {e}"
    ) from e


def _iter_before(tree: ExecutionChainStep):
    """Iterate over all 'before' hooks in a tree, including those from old main versions."""
    for old in tree.old_main:
        yield from old.before
    yield from tree.before


def _iter_after(tree: ExecutionChainStep):
    """Iterate over all 'after' hooks in a tree, including those from old main versions."""
    yield from tree.after
    for old in reversed(tree.old_main):
        yield from old.after


async def _run_async_steps(steps: list[ExecutionStep], ctx: APIContext, orig: Callable):
    """Execute a sequence of async and sync steps."""
    for s in steps:
        f, m, sctx = _setup_step(ctx, s)
        try:
            res = call_with_context(m, f, sctx, sctx.args, sctx.kwargs)
            if s.is_async:
                res = await res
            if sctx.is_main:
                sctx.result = res
        except Exception as e:
            _handle_exc(e, sctx, f, orig)
    return ctx.result


def _run_sync_steps(steps: list[ExecutionStep], ctx: APIContext, orig: Callable):
    """Execute a sequence of synchronous steps."""
    for s in steps:
        f, m, sctx = _setup_step(ctx, s)
        try:
            res = call_with_context(m, f, sctx, sctx.args, sctx.kwargs)
            if sctx.is_main:
                sctx.result = res
        except Exception as e:
            _handle_exc(e, sctx, f, orig)
    return ctx.result


def _evaluate_sync_tree(
    tree: ExecutionChainStep,
    ctx: APIContext,
    orig: Callable,
    wrapped_it: Optional[Callable] = None,
):
    """Execute a synchronous generator execution tree recursively."""
    main_step = tree.main

    def _wrapper():
        f, sctx = None, ctx
        try:
            for b in _iter_before(tree):
                yield from _evaluate_sync_tree(b, ctx, orig)
            rv = (
                (yield from wrapped_it)
                if (wrapped_it and main_step.generator_mode != "intercept")
                else None
            )
            f, m, sctx = _setup_step(ctx, main_step)
            if wrapped_it:
                sctx.original_generator = wrapped_it
            res = call_with_context(m, f, sctx, sctx.args, sctx.kwargs)
            if main_step.is_generator:
                main_res = yield from res
            else:
                main_res = res
            if sctx.is_main:
                sctx.result = main_res
            return (
                rv
                if (wrapped_it and main_step.generator_mode != "intercept")
                else main_res
            )
        except Exception as e:
            _handle_exc(e, sctx, f, orig)

    it = _wrapper()
    for a in _iter_after(tree):
        it = _evaluate_sync_tree(a, ctx, orig, wrapped_it=it)
    return it


def _evaluate_async_tree(
    tree: ExecutionChainStep,
    ctx: APIContext,
    orig: Callable,
    wrapped_it: Optional[Callable] = None,
):
    """Execute an asynchronous generator execution tree recursively."""
    main_step = tree.main

    async def _wrapper():
        f, sctx = None, ctx
        queue = [_evaluate_async_tree(b, ctx, orig) for b in _iter_before(tree)]
        if wrapped_it and main_step.generator_mode != "intercept":
            queue.append(wrapped_it)
        queue.append("MAIN")
        try:
            while queue:
                item = queue.pop(0)
                if item == "MAIN":
                    f, m, sctx = _setup_step(ctx, main_step)
                    if wrapped_it:
                        sctx.original_generator = wrapped_it
                    res = call_with_context(m, f, sctx, sctx.args, sctx.kwargs)
                    if not (main_step.is_generator or main_step.is_async_gen):
                        main_res = await res if main_step.is_async else res
                        if sctx.is_main:
                            sctx.result = main_res
                        continue
                    item = res
                it = _normalize_gen(item)
                op, v = it.asend, None
                while True:
                    try:
                        res_val = await op(v)
                        v = yield res_val
                        op = it.asend
                    except StopAsyncIteration:
                        break
                    except GeneratorExit:
                        await it.aclose()
                        raise
                    except BaseException as e:
                        op, v = it.athrow, e
        except Exception as e:
            _handle_exc(e, sctx, f, orig)

    it = _wrapper()
    for a in _iter_after(tree):
        it = _evaluate_async_tree(a, ctx, orig, wrapped_it=it)
    return it


def run_steps(
    steps: list[ExecutionStep],
    tree: ExecutionChainStep,
    ctx: APIContext,
    original_func: Callable,
):
    """Execute a chain of steps using the appropriate runner based on function traits."""
    main_step = tree.main
    if len(steps) == 1 and main_step.is_generator:
        f, m, sctx = _setup_step(ctx, main_step)
        try:
            return call_with_context(m, f, sctx, sctx.args, sctx.kwargs)
        except Exception as e:
            _handle_exc(e, sctx, f, original_func)
    if main_step.is_generator:
        return (
            _evaluate_async_tree(tree, ctx, original_func)
            if main_step.is_async
            else _evaluate_sync_tree(tree, ctx, original_func)
        )
    return (
        _run_async_steps(steps, ctx, original_func)
        if any(s.is_async for s in steps)
        else _run_sync_steps(steps, ctx, original_func)
    )
