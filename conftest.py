"""Apply test database isolation before pytest collects application tests."""

from _test_isolation import initialize_test_process

initialize_test_process()
