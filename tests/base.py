import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import stubs  # noqa: E402

stubs.install()

from database import core  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402
import enrichment  # noqa: E402


class DBCase(unittest.IsolatedAsyncioTestCase):
    """Each test gets a clean in-memory MongoDB."""

    def setUp(self):
        self.db = FakeDB()
        core.use(self.db)
        enrichment._queued.clear()
        enrichment.progress.update(total=0, done=0, failed=0)
