import pytest
from conftest import create_system, target, reg, V


class TestInvokeException:
    def test_original_function_exception_reraised(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="fail")
        def fail():
            raise ValueError("original error")

        reg((a, s_a))

        with pytest.raises(ValueError, match="original error") as excinfo:
            fail()
        # Ensure it's not wrapped in RuntimeError
        assert excinfo.type is ValueError

    def test_hook_exception_wrapped(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="work")
        def work():
            return "success"

        @s_b.hook(target("work"), when="before")
        def before_work():
            raise ValueError("hook error")

        reg((a, s_a), (b, s_b))

        with pytest.raises(RuntimeError) as excinfo:
            work()

        assert "Exception in hook function before_work of Addon B: hook error" in str(
            excinfo.value
        )
        assert isinstance(excinfo.value.__cause__, ValueError)

    def test_override_exception_wrapped(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="work", version=V(1, 0, 0))
        def work():
            return "success"

        @s_b.override(target("work"))
        def override_work():
            raise ValueError("override error")

        reg((a, s_a), (b, s_b))

        with pytest.raises(RuntimeError) as excinfo:
            work()

        assert (
            "Exception in active function override_work of Addon B: override error"
            in str(excinfo.value)
        )
        assert isinstance(excinfo.value.__cause__, ValueError)

    def test_after_hook_exception_wrapped(self, two_addons):
        (a, s_a), (b, s_b) = two_addons

        @s_a.function(name="work")
        def work():
            return "success"

        @s_b.hook(target("work"), when="after")
        def after_work():
            raise ValueError("after error")

        reg((a, s_a), (b, s_b))

        with pytest.raises(RuntimeError) as excinfo:
            work()

        assert "Exception in hook function after_work of Addon B: after error" in str(
            excinfo.value
        )
