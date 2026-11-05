import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ("lkr", "lkr_dev_cli", "scripts", "tests")


def _has_plain_dict(annotation: ast.AST) -> bool:
    subscripted = {
        id(n.value) for n in ast.walk(annotation) if isinstance(n, ast.Subscript)
    }
    return any(
        isinstance(n, ast.Name)
        and n.id in ("dict", "Dict")
        and id(n) not in subscripted
        for n in ast.walk(annotation)
    )


def _iter_annotations(tree: ast.AST) -> list[tuple[int, ast.AST]]:
    out: list[tuple[int, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                node.args.vararg,
                node.args.kwarg,
            ):
                if arg and arg.annotation:
                    out.append((arg.lineno, arg.annotation))
            if node.returns:
                out.append((node.lineno, node.returns))
        elif isinstance(node, ast.AnnAssign) and node.annotation:
            out.append((node.lineno, node.annotation))
        elif isinstance(node, ast.TypeAlias):
            out.append((node.lineno, node.value))
    return out


def test_no_plain_dict_annotations() -> None:
    violations = [
        f"{py_file.relative_to(REPO_ROOT)}:{line}: plain dict in '{ast.unparse(ann)}'"
        for folder in TARGET_DIRS
        if (REPO_ROOT / folder).exists()
        for py_file in sorted((REPO_ROOT / folder).rglob("*.py"))
        for line, ann in _iter_annotations(
            ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        )
        if _has_plain_dict(ann)
    ]
    assert not violations, (
        "Plain unparameterized 'dict' annotations are disallowed; use TypedDict, BaseModel, or dict[K, V]:\n"
        + "\n".join(violations)
    )
