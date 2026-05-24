"""M4.2 — read-only ontology logic tools."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


class FunctionNotFoundError(LookupError):
    """Raised when ontology/functions/<name>.py can't be imported."""


class FunctionInvocationError(RuntimeError):
    """Wraps an exception raised by the invoked function."""

    def __init__(self, function_name: str, cause: Exception) -> None:
        super().__init__(f"{function_name} raised {type(cause).__name__}: {cause}")
        self.cause = cause


def list_functions(workspace: Path) -> list[dict[str, Any]]:
    """Return one dict per FunctionType declaration."""
    from agent_readiness.ontology.loader import load_ontology

    ont = load_ontology(workspace / "ontology")
    functions_dir = workspace / "ontology" / "functions"
    out: list[dict[str, Any]] = []
    for name, fn_type in ont.functions.items():
        spec = fn_type.spec or {}
        out.append(
            {
                "name": name,
                "signature": {
                    "params": spec.get("inputs", []),
                    "returns": spec.get("outputs", []),
                },
                "has_implementation": (functions_dir / f"{name}.py").is_file(),
            }
        )
    return out


def invoke_function(workspace: Path, function_name: str, **kwargs: Any) -> Any:
    """Dynamically import and call ``ontology/functions/<function_name>.py``."""
    func_path = workspace / "ontology" / "functions" / f"{function_name}.py"
    if not func_path.is_file():
        raise FunctionNotFoundError(
            f"Function not implemented: {function_name} "
            f"(expected at {func_path}). Run "
            f"`agent-readiness ontology bootstrap propose-functions . "
            f"--function-type {function_name}`."
        )
    spec = importlib.util.spec_from_file_location(
        f"ontology_function_{function_name}", func_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    try:
        fn = getattr(module, function_name)
    except AttributeError as exc:
        raise FunctionNotFoundError(
            f"Function module {func_path} does not export `{function_name}`"
        ) from exc
    try:
        return fn(ontology_root=workspace / "ontology", **kwargs)
    except Exception as exc:
        raise FunctionInvocationError(function_name, exc) from exc
