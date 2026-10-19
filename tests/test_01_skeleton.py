import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Skeleton(unittest.TestCase):
    def test_missing_bot_token_stops_with_clear_message(self):
        env = {k: v for k, v in os.environ.items() if k not in ("BOT_TOKEN", "API_ID", "API_HASH", "DATABASE_URI", "ADMINS", "LOG_CHANNEL", "CHANNELS")}
        env["API_ID"], env["API_HASH"], env["DATABASE_URI"] = "1", "x", "mongodb://x"
        env["ADMINS"], env["LOG_CHANNEL"], env["CHANNELS"] = "1", "-100", "-100"
        r = subprocess.run([sys.executable, "bot.py"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Missing environment variables: BOT_TOKEN", r.stderr)
        self.assertIn("Render", r.stderr)

    def test_boolean_parsing(self):
        env = dict(os.environ, AUTO_DELETE="False", PM_SEARCH="no", IMDB="0", BUTTON_MODE="TRUE", MAX_BTN="on", PROTECT_CONTENT="Yes")
        code = "import info;print(info.AUTO_DELETE,info.PM_SEARCH,info.IMDB,info.BUTTON_MODE,info.MAX_BTN,info.PROTECT_CONTENT)"
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ["False", "False", "False", "True", "True", "True"])

    def test_no_secret_has_a_default(self):
        env = {k: v for k, v in os.environ.items() if k not in ("BOT_TOKEN", "API_HASH", "DATABASE_URI", "SECRET_KEY", "WEB_ADMIN_PASSWORD", "TMDB_API_KEY")}
        code = "import info;print(repr((info.BOT_TOKEN,info.API_HASH,info.DATABASE_URI,info.SECRET_KEY,info.WEB_ADMIN_PASSWORD,info.TMDB_API_KEY)))"
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "('', '', '', '', '', '')")

    def test_multi_tokens_collected_in_order(self):
        env = dict(os.environ, MULTI_TOKEN2="b", MULTI_TOKEN1="a", MULTI_TOKEN10="j")
        r = subprocess.run([sys.executable, "-c", "import info;print(info.MULTI_TOKENS)"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "['a', 'b', 'j']")


if __name__ == "__main__":
    unittest.main()
