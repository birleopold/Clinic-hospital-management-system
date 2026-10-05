"""Dependency-free safety/structure checks; does not launch an app or browser."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('browser_ci_review', ROOT / 'scripts/browser_ci_review.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class BrowserHarnessTests(unittest.TestCase):
    def test_embedded_python_compiles(self):
        for name in ('SETTINGS', 'SERVER', 'SEED', 'VERIFY'):
            with self.subTest(name=name):
                compile(getattr(harness, name), name, 'exec')

    def test_mfa_verification_is_limited_to_exact_fixture_accounts(self):
        # django-guardian's framework AnonymousUser must not be treated as a
        # synthetic login account or counted as needing an enrolled TOTP device.
        self.assertIn("Path(os.environ['BROWSER_CI_RESULT']).read_text()", harness.VERIFY)
        self.assertIn("fixture['admin']", harness.VERIFY)
        self.assertIn("account['username'] for account in fixture['accounts']", harness.VERIFY)
        self.assertIn('for username in fixture_usernames:', harness.VERIFY)
        self.assertIn('User.objects.get(username=username)', harness.VERIFY)
        self.assertIn('TOTPDevice.objects.filter(user_id=user.pk, confirmed=True).count() == 1', harness.VERIFY)
        self.assertNotIn('User.objects.count()', harness.VERIFY)

    def test_owner_control_redirect_is_separate_from_strict_page_matrix(self):
        source = (ROOT / 'scripts/browser_ci_review.cjs').read_text()
        function = re.search(r'async function verifyOwnerLanding\(page, baseURL\) \{.*?\n\}', source, re.S).group()
        matrix = re.search(r"await pageMatrix\(page, baseURL, \[(.*?)\], 'owner'\)", source, re.S).group(1)
        self.assertNotIn('/accounts/control/', matrix)
        self.assertIn('await verifyOwnerLanding(page, baseURL)', source)
        # Execute only the small helper with browser-free stubs. Both success
        # and wrong-destination failure are tested without requiring Playwright.
        script = "const assert = require('node:assert/strict');\n" + function + '''
(async () => {
  const base = 'http://127.0.0.1:12345';
  const page = {
    goto: async value => { assert.equal(value, base + '/accounts/control/'); return {status: () => 200}; },
    url: () => base + '/accounts/tenants/',
  };
  await verifyOwnerLanding(page, base);
  await assert.rejects(() => verifyOwnerLanding({...page, url: () => base + '/accounts/login/'}, base));
  await assert.rejects(() => verifyOwnerLanding({...page, goto: async () => ({status: () => 403})}, base));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
'''
        subprocess.run(['node', '-e', script], check=True, timeout=10)

    def test_environment_excludes_credentials_and_external_settings(self):
        incoming = {
            'PATH': '/usr/bin', 'HOME': '/tmp/synthetic-home', 'LANG': 'C.UTF-8',
            'DATABASE_URL': 'must-not-inherit', 'TEST_DATABASE_URL': 'must-not-inherit',
            'DJANGO_SETTINGS_MODULE': 'production', 'DJANGO_SECRET_KEY': 'must-not-inherit',
            'TENANT_KEY': 'must-not-inherit', 'TENANT_CONTROL_ORIGIN': 'must-not-inherit',
            'GITHUB_TOKEN': 'must-not-inherit', 'AWS_ACCESS_KEY_ID': 'must-not-inherit',
            'HTTP_PROXY': 'must-not-inherit', 'HTTPS_PROXY': 'must-not-inherit',
            'NODE_OPTIONS': 'must-not-inherit', 'PYTHONPATH': 'must-not-inherit',
        }
        with patch.dict(os.environ, incoming, clear=True):
            self.assertEqual(harness.clean_environment(), {
                'PATH': '/usr/bin', 'HOME': '/tmp/synthetic-home', 'LANG': 'C.UTF-8',
            })

    def test_commands_use_selected_interpreter_and_private_output(self):
        environment = {'BROWSER_CI_DATABASE': '/tmp/disposable.sqlite3'}
        with patch.object(harness.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            harness.python_command(['manage.py', 'check'], environment, label='test')
        args, kwargs = run.call_args
        self.assertEqual(args[0], [harness.sys.executable, 'manage.py', 'check'])
        self.assertEqual(kwargs['env'], environment)
        self.assertEqual(kwargs['cwd'], ROOT)
        self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(kwargs['timeout'], 120)

    def test_failed_commands_do_not_report_private_output(self):
        with patch.object(harness.subprocess, 'run', return_value=Mock(returncode=2)):
            with self.assertRaisesRegex(RuntimeError, 'synthetic seed failed'):
                harness.python_command(['-c', 'private source'], {}, label='synthetic seed')

    def test_dead_server_fails_before_http_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(harness, 'build_opener') as opener:
                with self.assertRaisesRegex(RuntimeError, 'exited before becoming ready'):
                    harness.wait_for_server(Mock(poll=Mock(return_value=1)), Path(folder) / 'port')
                opener.return_value.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()
