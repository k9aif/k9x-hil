"""Make the script-style check() helpers real pytest failures.

Each test module records failed checks in a module-level `failures` list
(so it can also run as a plain script via its own main()). Under pytest
nothing ever asserted on that list, so a failing check still reported
"passed". This fixture clears the list before each test and fails the test
if any check recorded a failure during it.
"""

import pytest


@pytest.fixture(autouse=True)
def _fail_on_recorded_check_failures(request):
    failures = getattr(request.module, "failures", None)
    if failures is None:
        yield
        return
    before = len(failures)
    yield
    new = failures[before:]
    if new:
        pytest.fail(f"check(s) failed: {new}", pytrace=False)
