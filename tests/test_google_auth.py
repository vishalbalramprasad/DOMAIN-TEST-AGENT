import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import main


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(main, "DB", os.path.join(self.temp_dir.name, "test.db"))
        self.db_patch.start()
        main.init()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_authorization_url_uses_state_and_pkce(self):
        url = main.google_authorization_url(
            "client-id", "http://127.0.0.1:8765/auth/google/callback", "csrf-state", "pkce-verifier"
        )
        params = parse_qs(urlsplit(url).query)

        self.assertEqual("csrf-state", params["state"][0])
        self.assertEqual("S256", params["code_challenge_method"][0])
        self.assertEqual("openid email profile", params["scope"][0])
        self.assertNotIn("client_secret", params)

    def test_render_redirect_uri_is_derived_from_public_url(self):
        with patch.dict(os.environ, {
            "GOOGLE_REDIRECT_URI": "",
            "RENDER_EXTERNAL_URL": "https://domain-test-agent.onrender.com/",
        }):
            _, _, redirect_uri = main.google_config()

        self.assertEqual(
            "https://domain-test-agent.onrender.com/auth/google/callback",
            redirect_uri,
        )

    def test_secure_cookie_is_enabled_only_in_production(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "RENDER": ""}, clear=False):
            self.assertEqual("; Secure", main.secure_cookie())
        with patch.dict(os.environ, {"APP_ENV": "development", "RENDER": ""}, clear=False):
            self.assertEqual("", main.secure_cookie())

    def test_production_does_not_create_default_admin(self):
        production_db = os.path.join(self.temp_dir.name, "production.db")
        with patch.object(main, "DB", production_db), patch.dict(
            os.environ, {"APP_ENV": "production", "ADMIN_INITIAL_PASSWORD": ""}, clear=False
        ):
            main.init()
            with main.db() as connection:
                admin = connection.execute("select 1 from users where name='admin'").fetchone()

        self.assertIsNone(admin)

    def test_google_account_is_created_once_for_provider_subject(self):
        first = main.create_google_user("google-subject-123", "new.user@example.com")
        second = main.create_google_user("google-subject-123", "changed.email@example.com")

        self.assertEqual(first, second)
        with main.db() as connection:
            row = connection.execute(
                "select name, google_sub from users where google_sub=?",
                ("google-subject-123",),
            ).fetchone()
        self.assertEqual((first, "google-subject-123"), row)

    def test_google_username_collision_gets_a_unique_name(self):
        name = main.create_google_user("google-admin-subject", "admin@example.com")

        self.assertNotEqual("admin", name)
        self.assertLessEqual(len(name), 20)
        with main.db() as connection:
            self.assertIsNotNone(
                connection.execute("select 1 from users where google_sub=?", ("google-admin-subject",)).fetchone()
            )

    def test_legacy_users_table_is_migrated(self):
        legacy_db = os.path.join(self.temp_dir.name, "legacy.db")
        with patch.object(main, "DB", legacy_db):
            with main.db() as connection:
                connection.execute("create table users(name text primary key, salt text, hash text)")
            main.init()
            with main.db() as connection:
                columns = {row[1] for row in connection.execute("pragma table_info(users)")}

        self.assertIn("google_sub", columns)


if __name__ == "__main__":
    unittest.main()
