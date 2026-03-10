import pytest
import inspect
from conftest import reg


class TestSignaturePreservation:
    def test_kw_only_preservation(self, one_addon):
        a, s = one_addon

        @s.function()
        def kw_func(*, a, b=1):
            return a + b

        reg((a, s))

        # Check signature via introspection
        sig = inspect.signature(kw_func)
        assert "a" in sig.parameters
        assert sig.parameters["a"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["b"].default == 1

        # Check calling
        assert kw_func(a=10) == 11
        with pytest.raises(TypeError):
            kw_func(10)  # Should fail because it's kw-only

    def test_pos_only_preservation(self, one_addon):
        a, s = one_addon

        @s.function()
        def pos_only(a, /, b):
            return a + b

        reg((a, s))

        sig = inspect.signature(kw_func if False else pos_only)
        real_sig = inspect.signature(pos_only, follow_wrapped=False)
        assert "a" in real_sig.parameters
        assert real_sig.parameters["a"].kind == inspect.Parameter.POSITIONAL_ONLY

        assert pos_only(1, b=2) == 3
        with pytest.raises(TypeError):
            pos_only(a=1, b=2)  # Should fail because 'a' is pos-only

    def test_complex_signature_preservation(self, one_addon):
        a, s = one_addon

        @s.function()
        def complex_func(p1, /, p2, p3=3, *args, k1, k2=2, **kwargs):
            return {
                "p1": p1,
                "p2": p2,
                "p3": p3,
                "args": args,
                "k1": k1,
                "k2": k2,
                "kwargs": kwargs,
            }

        reg((a, s))

        sig = inspect.signature(complex_func, follow_wrapped=False)
        params = list(sig.parameters.values())

        assert params[0].name == "p1"
        assert params[0].kind == inspect.Parameter.POSITIONAL_ONLY

        assert params[1].name == "p2"
        assert params[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD

        assert params[2].name == "p3"
        assert params[2].default == 3

        assert params[3].kind == inspect.Parameter.VAR_POSITIONAL

        assert params[4].name == "k1"
        assert params[4].kind == inspect.Parameter.KEYWORD_ONLY

        assert params[5].name == "k2"
        assert params[5].default == 2

        assert params[6].kind == inspect.Parameter.VAR_KEYWORD

        res = complex_func(1, 2, 4, 5, 6, k1=7, extra=8)
        assert res == {
            "p1": 1,
            "p2": 2,
            "p3": 4,
            "args": (5, 6),
            "k1": 7,
            "k2": 2,
            "kwargs": {"extra": 8},
        }
