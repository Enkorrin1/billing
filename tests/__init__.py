"""Test package bootstrap for ``python -m tests.test_...`` entrypoints."""

from _test_isolation import initialize_test_process, is_test_invocation

if is_test_invocation():
    initialize_test_process()
