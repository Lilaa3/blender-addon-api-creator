from conftest import create_system


def test_function_with_args_argument():
    a, s = create_system("Addon A", {}, "addon_a", ("core",))

    @s.function(name="fn_with_args_param")
    def fn_with_args_param(args):
        return args

    a.register_system(s)
    assert fn_with_args_param(123) == 123


def test_function_with_kwargs_argument():
    a, s = create_system("Addon A", {}, "addon_a", ("core",))

    @s.function(name="fn_with_kwargs_param")
    def fn_with_kwargs_param(kwargs):
        return kwargs

    a.register_system(s)
    assert fn_with_kwargs_param(456) == 456
