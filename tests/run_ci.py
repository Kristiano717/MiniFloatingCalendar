"""Run the tests; on GitHub Actions, report each failure as an annotation so it shows on the run page."""
import os
import sys
import unittest

here = os.path.dirname(os.path.abspath(__file__))
suite = unittest.defaultTestLoader.discover(here)
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, tb in result.failures + result.errors:
    last = [line for line in tb.strip().splitlines() if line.strip()][-1]
    msg = (str(test) + " :: " + last).replace("%", "%25").replace("\r", "").replace("\n", " ")
    print(f"::error title=Test failed::{msg}")
sys.exit(0 if result.wasSuccessful() else 1)
