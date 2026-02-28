import ast
import os
import random
from typing import Any

from pathlib import Path
from swebench.harness.constants import FAIL_TO_PASS
from swesmith.profiles import registry


# File extensions recognized as JavaScript/TypeScript
_JS_TS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def extract_pytest_test(
    file_path: str | Path, test_name: str, class_name: str | None = None
) -> str | None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception:
        return None

    # If class_name is provided, look inside the class
    if class_name:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name == test_name:
                        return ast.unparse(method)  # Extract function from class
    else:
        # Look for a top-level function
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == test_name:
                return ast.unparse(node)  # Extract function

    return None


def extract_js_ts_test_file(file_path: str | Path) -> str | None:
    """
    Extract the full content of a JavaScript/TypeScript test file.

    Unlike Python where we can extract individual test functions via AST,
    JS/TS test frameworks (Jest/Vitest/Mocha) use describe/it/test blocks
    that are harder to extract individually. Instead, return the full file
    content (truncated if needed) so the LLM has test context.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Truncate very long files to keep prompt manageable
        max_chars = 5000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n// ... (truncated) ..."
        return content
    except Exception:
        return None


def _is_js_ts_test_name(test: str) -> bool:
    """Check if a test name looks like a JS/TS file path (as opposed to a pytest path)."""
    return any(test.rstrip().endswith(ext) for ext in _JS_TS_EXTS)


def get_test_function(instance: dict, idx: int | None = None) -> dict[str, Any]:
    # Pick a test from FAIL_TO_PASS
    test = (
        random.choice(instance[FAIL_TO_PASS])
        if idx is None
        else instance[FAIL_TO_PASS][idx]
        if idx < len(instance[FAIL_TO_PASS])
        else instance[FAIL_TO_PASS][-1]
    )

    # Clone repo for instance
    repo = instance["repo"]
    repo_name = repo.split("/")[-1]
    cloned = registry.get(repo_name).clone()

    # Detect if this is a JS/TS test (file path) or a pytest test (:: format)
    if _is_js_ts_test_name(test):
        # JS/TS: test name is a file path like "test/foo.test.ts"
        test_file = os.path.join(repo_name, test.strip())
        return {
            "test_src": extract_js_ts_test_file(test_file),
            "test_file": test_file,
            "test_name": test.strip(),
            "class_name": None,
            "repo_name": repo_name,
            "cloned": cloned,
        }

    # Python/pytest: test names are in format test_file::test_name or just test_name
    class_name = None
    if "::" not in test:
        test_file = "test.py"
        test_name = test.split()[0]
    else:
        test_file, test_name = test.split("::", 1)
        if "::" in test_name:
            class_name, test_name = test_name.split("::", 1)
        # Remove any parameters from the test name
        test_name = test_name.split("[")[0]

    # Update test_file to be relative to the repo
    test_file = os.path.join(repo_name, test_file)

    return {
        "test_src": extract_pytest_test(test_file, test_name, class_name),
        "test_file": test_file,
        "test_name": test_name,
        "class_name": class_name,
        "repo_name": repo_name,
        "cloned": cloned,
    }
