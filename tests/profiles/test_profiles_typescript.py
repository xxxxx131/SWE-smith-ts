from swesmith.profiles.javascript import parse_log_jest, parse_log_vitest
from swebench.harness.constants import TestStatus


def test_parse_log_vitest_basic():
    log = """
✓ src/utils.test.ts (5 tests) 12ms
✓ src/core.test.ts (10 tests) 25ms
"""
    result = parse_log_vitest(log)
    assert len(result) == 2
    assert result["src/utils.test.ts"] == TestStatus.PASSED.value
    assert result["src/core.test.ts"] == TestStatus.PASSED.value


def test_parse_log_vitest_with_failures():
    log = """
✓ src/utils.test.ts (5 tests) 12ms
✗ src/core.test.ts (3 tests | 2 failed) 25ms
"""
    result = parse_log_vitest(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    failed_count = sum(1 for v in result.values() if v == TestStatus.FAILED.value)
    assert passed_count == 1
    assert failed_count == 1


def test_parse_log_vitest_no_matches():
    log = """
Some random text
No test results here
"""
    result = parse_log_vitest(log)
    assert result == {}


def test_parse_log_vitest_suite_level_pass_fail():
    log = """
PASS src/utils.test.ts
FAIL src/core.test.ts [ src/core.test.ts ]
"""
    result = parse_log_vitest(log)
    assert result["src/utils.test.ts"] == TestStatus.PASSED.value
    assert result["src/core.test.ts"] == TestStatus.FAILED.value


def test_parse_log_vitest_with_ansi_sequences():
    log = (
        "\x1b[31mFAIL\x1b[0m src/compile-error.test.ts [ src/compile-error.test.ts ]\n"
        "\x1b[32m✓\x1b[0m src/happy-path.test.ts (3 tests) 12ms\n"
    )
    result = parse_log_vitest(log)
    assert result["src/compile-error.test.ts"] == TestStatus.FAILED.value
    assert result["src/happy-path.test.ts"] == TestStatus.PASSED.value


def test_parse_log_vitest_prefers_failed_on_conflict():
    log = """
FAIL src/conflict.test.ts
PASS src/conflict.test.ts
"""
    result = parse_log_vitest(log)
    assert result["src/conflict.test.ts"] == TestStatus.FAILED.value


def test_parse_log_vitest_ignores_assertion_noise_lines():
    log = """
✓ Expected: 2
✗ src/core.test.ts (3 tests | 1 failed) 25ms
"""
    result = parse_log_vitest(log)
    assert "Expected: 2" not in result
    assert result["src/core.test.ts"] == TestStatus.FAILED.value


def test_parse_log_jest_basic():
    log = """
  ✓ should add numbers (5ms)
  ✓ should subtract numbers (3ms)
  ✓ should multiply numbers (2ms)
"""
    result = parse_log_jest(log)
    assert len(result) == 3
    assert result["should add numbers"] == TestStatus.PASSED.value
    assert result["should subtract numbers"] == TestStatus.PASSED.value
    assert result["should multiply numbers"] == TestStatus.PASSED.value


def test_parse_log_jest_with_failures():
    log = """
  ✓ should add numbers (5ms)
  ✕ should subtract numbers (3ms)
  ✓ should multiply numbers (2ms)
"""
    result = parse_log_jest(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    failed_count = sum(1 for v in result.values() if v == TestStatus.FAILED.value)
    assert passed_count == 2
    assert failed_count == 1


def test_parse_log_jest_with_skipped():
    log = """
  ✓ should add numbers (5ms)
  ○ should subtract numbers
  ✓ should multiply numbers (2ms)
"""
    result = parse_log_jest(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    skipped_count = sum(1 for v in result.values() if v == TestStatus.SKIPPED.value)
    assert passed_count == 2
    assert skipped_count == 1


def test_parse_log_jest_no_matches():
    log = """
Some random text
No test results here
"""
    result = parse_log_jest(log)
    assert result == {}


def test_parse_log_jest_suite_level_pass_fail():
    log = """
PASS src/__tests__/string.test.ts (6.321 s)
FAIL src/__tests__/object.test.ts (2.104 s)
"""
    result = parse_log_jest(log)
    assert result["src/__tests__/string.test.ts"] == TestStatus.PASSED.value
    assert result["src/__tests__/object.test.ts"] == TestStatus.FAILED.value


def test_parse_log_jest_with_ansi_sequences():
    log = (
        "\x1b[31mFAIL\x1b[0m src/__tests__/typed.test.ts\n"
        "  \x1b[32m✓\x1b[0m should parse schema (3ms)\n"
    )
    result = parse_log_jest(log)
    assert result["src/__tests__/typed.test.ts"] == TestStatus.FAILED.value
    assert result["should parse schema"] == TestStatus.PASSED.value


def test_parse_log_jest_prefers_failed_on_conflict():
    log = """
FAIL src/__tests__/conflict.test.ts
PASS src/__tests__/conflict.test.ts
"""
    result = parse_log_jest(log)
    assert result["src/__tests__/conflict.test.ts"] == TestStatus.FAILED.value
