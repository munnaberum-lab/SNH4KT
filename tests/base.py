import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import stubs  # noqa: E402

stubs.install()

import info  # noqa: E402
info.SECRET_KEY = "unit-test-secret-key-not-for-production"
from database import accounts, core, files  # noqa: E402
import config  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402
import enrichment  # noqa: E402


class DBCase(unittest.IsolatedAsyncioTestCase):
    """Each test gets a clean in-memory MongoDB."""

    def setUp(self):
        self.db = FakeDB()
        for name, fields in (("accounts", ("aid",)), ("likes", ("uid", "sid"))):
            self.db[name].add_unique(*fields)
        core.use(self.db)
        config.invalidate()
        accounts._has._d.clear()
        accounts._ver._d.clear()
        files.reset_caches()
        enrichment._queued.clear()
        enrichment.progress.update(total=0, done=0, failed=0)
