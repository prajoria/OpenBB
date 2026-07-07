"""E0.1 split verification: compiler_errors.py owns compiler+runtime errors;
errors.py owns provider-side errors; both paths still work for one release."""


def test_compiler_errors_module_exports_move_list() -> None:
    from openbb_pine import compiler_errors
    expected = {
        "PineError", "Diagnostic", "PineCompileError", "PineSyntaxError",
        "PineTypeError", "PineUnsupportedBuiltinError",
        "PineUnsupportedFeatureError", "PineCodegenError",
        "PineInternalCompilerError", "PineCacheError",
        "PineRuntimeError", "PineStrategyNotYetImplementedError",
        "PineSecurityError", "PineExecTimeoutError",
        "PineDataResolverError", "PineSecurityContextNotFoundError",
    }
    missing = expected - set(dir(compiler_errors))
    assert not missing, f"compiler_errors missing: {missing}"


def test_errors_module_still_exports_provider_errors() -> None:
    from openbb_pine import errors
    for name in (
        "PineProviderError", "PineFMPRequiredError",
        "PineFMPUnreachableError", "PineDataValidationError",
    ):
        assert hasattr(errors, name), f"errors missing STAY symbol: {name}"


def test_errors_module_still_reexports_compiler_symbols_for_one_release() -> None:
    # Old callers `from openbb_pine.errors import PineSyntaxError` must keep working.
    from openbb_pine import errors, compiler_errors
    assert errors.PineSyntaxError is compiler_errors.PineSyntaxError
    assert errors.PineDataResolverError is compiler_errors.PineDataResolverError
    assert errors.PineSecurityContextNotFoundError is compiler_errors.PineSecurityContextNotFoundError


def test_provider_errors_are_NOT_in_compiler_errors() -> None:
    from openbb_pine import compiler_errors
    for provider_only in ("PineFMPRequiredError", "PineFMPUnreachableError", "PineDataValidationError"):
        assert not hasattr(compiler_errors, provider_only), (
            f"{provider_only} is provider-side, must NOT leak into compiler_errors"
        )
