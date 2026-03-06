import pytest
import sys
import types
from blender_api_lib.api_types import APIContext
from blender_api_lib.registry import get_registry
from conftest import reg, target


class TestUnstableHash:
    def test_stable_function_hash(self, one_addon):
        a, s = one_addon
        hashes_received = {}

        @s.function(unstable=False)
        def stable_func():
            return "ok"

        @s.hook(target("stable_func", None), when="before")
        def capture_stable(ctx: APIContext):
            nonlocal hashes_received
            hashes_received = ctx.unstable_hashes.copy()

        reg((a, s))

        stable_func()
        assert "stable_func" not in hashes_received

    def test_unstable_function_hash(self, one_addon):
        a, s = one_addon
        hashes_received = {}

        @s.function(unstable=True)
        def unstable_func():
            return "ok"

        @s.hook(target("unstable_func", None), when="before")
        def capture_unstable(ctx: APIContext):
            nonlocal hashes_received
            hashes_received = ctx.unstable_hashes.copy()

        reg((a, s))

        unstable_func()
        assert (
            hashes_received.get("unstable_func")
            == "4a34afbbe0b5147978542c24b00d8d39536049b7430b3e7ef2f42ab674e51ee9"
        )

        a, s = one_addon

        @s.function(unstable=True)
        def unstable_func2():
            return "ok"

        @s.hook(target("unstable_func2", None), when="before")
        def capture_unstable_2(ctx: APIContext):
            nonlocal hashes_received
            hashes_received = ctx.unstable_hashes.copy()

        reg((a, s))

        unstable_func2()
        assert (
            hashes_received.get("unstable_func2")
            == "4a34afbbe0b5147978542c24b00d8d39536049b7430b3e7ef2f42ab674e51ee9"
        )

        a, s = one_addon

        @s.function(unstable=True)
        def unstable_func3():
            return "ok-y"

        @s.hook(target("unstable_func3", None), when="before")
        def capture_unstable_3(ctx: APIContext):
            nonlocal hashes_received
            hashes_received = ctx.unstable_hashes.copy()

        reg((a, s))

        unstable_func3()
        assert (
            hashes_received.get("unstable_func3")
            != "4a34afbbe0b5147978542c24b00d8d39536049b7430b3e7ef2f42ab674e51ee9"
        )
        assert (
            hashes_received.get("unstable_func3")
            == "1ac9c4567e7d044ffdce8366e95579f4d183b9a82bc91dc49e0e11959084c518"
        )

    def test_hash_validation_constraints(self, two_addons, caplog):
        # Test Warning (default)
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(unstable=True)
        def target_func_warn():
            return "base"

        reg((a, s_a))

        caplog.clear()
        hashes_received = {}
        t_warn = target("target_func_warn")
        t_warn.expected_hashes = ["wrong_hash"]

        @s_b.hook(t_warn, when="before")
        def warn_hook(ctx: APIContext):
            nonlocal hashes_received
            hashes_received["warn_hook"] = True

        reg((a, s_a), (b, s_b))
        target_func_warn()
        assert "warn_hook" in hashes_received  # Should still run as it's just a warning
        assert any(
            'In hook "warn_hook": WARNING: Hash mismatch for "target_func_warn"'
            in rec.message
            and rec.levelname == "WARNING"
            for rec in caplog.records
        )

        # Test Error (blocked)
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(unstable=True)
        def target_func_err():
            return "base"

        reg((a, s_a))

        caplog.clear()
        hashes_received = {}
        t_err = target("target_func_err")
        t_err.expected_hashes = ["wrong_hash"]
        t_err.error_on_hash_mismatch = True

        @s_b.hook(t_err, when="before")
        def err_hook(ctx: APIContext):
            nonlocal hashes_received
            hashes_received["err_hook"] = True

        reg((a, s_a), (b, s_b))
        with pytest.raises(
            RuntimeError,
            match='In hook "err_hook": Hash mismatch for "target_func_err"',
        ):
            target_func_err()
        assert "err_hook" not in hashes_received  # Should be blocked

        # Test Success
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(unstable=True)
        def target_func_ok():
            return "base"

        reg((a, s_a))

        reg_obj = get_registry()
        runtime_sys = reg_obj._get_runtime_system(a.addon_path, s_a.system_name)
        assert runtime_sys is not None
        registry_hash = runtime_sys.functions["target_func_ok"].hash

        caplog.clear()
        hashes_received = {}
        t_ok = target("target_func_ok")
        t_ok.expected_hashes = [registry_hash]
        t_ok.error_on_hash_mismatch = True

        @s_b.hook(t_ok, when="before")
        def ok_hook(ctx: APIContext):
            nonlocal hashes_received
            hashes_received["ok_hook"] = True

        reg((a, s_a), (b, s_b))
        target_func_ok()
        assert "ok_hook" in hashes_received  # Should run
        assert not any('In hook "ok_hook":' in rec.message for rec in caplog.records)
