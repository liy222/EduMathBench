"""Credential loading uses synthetic values and never invokes a provider."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eval_credentials import CredentialFileError, KEY_NAMES, load_project_env


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="emb-env-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, text):
        (self.root / ".env.local").write_text(text, encoding="utf-8-sig")

    def test_blank_template_creates_no_fake_credentials(self):
        self.write("\n".join(name + "=" for name in KEY_NAMES))
        env = {}
        report = load_project_env(self.root, env)
        self.assertEqual(env, {})
        self.assertFalse(any(report["variables"].values()))

    def test_literal_values_are_not_executed_expanded_or_reported(self):
        secret = "$(example-never-run)=$EXAMPLE"
        self.write("DEEPSEEK_API_KEY='" + secret + "'\nDASHSCOPE_API_KEY=synthetic-second\n")
        env = {}
        report = load_project_env(self.root, env)
        self.assertEqual(env["DEEPSEEK_API_KEY"], secret)
        self.assertTrue(report["variables"]["DASHSCOPE_API_KEY"])
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("synthetic-second", json.dumps(report))

    def test_existing_environment_has_priority(self):
        self.write("ARK_API_KEY=synthetic-local\n")
        env = {"ARK_API_KEY": "synthetic-existing"}
        load_project_env(self.root, env)
        self.assertEqual(env["ARK_API_KEY"], "synthetic-existing")

    def test_invalid_file_never_partially_sets_environment(self):
        for invalid in ("PATH=synthetic-secret", "ARK_API_KEY=again", "invalid-secret-line", "MINIMAX_API_KEY='unclosed-secret", "ZHIPU_API_KEY=has space"):
            with self.subTest(invalid=invalid):
                self.write("ARK_API_KEY=first-secret\n" + invalid + "\n")
                env = {}
                with self.assertRaises(CredentialFileError) as error:
                    load_project_env(self.root, env)
                self.assertEqual(env, {})
                self.assertNotIn("secret", str(error.exception))

    def test_missing_file_is_allowed(self):
        report = load_project_env(self.root, {})
        self.assertFalse(report["credential_file_exists"])


if __name__ == "__main__":
    unittest.main()
