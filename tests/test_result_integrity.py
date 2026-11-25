import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.common import digest
from llm_eval.reporting.integrity import COMPATIBILITY_FILE, verify_results
from llm_eval.reporting.publish import git, publish_report
from tests import test_legal_publication as legal_fixtures


ROOT = Path(__file__).resolve().parents[1]


class ArchiveTests(unittest.TestCase):
    def test_fresh_checkout_and_fail_closed_historical_and_new_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'checkout'
            subprocess.run(['git', 'clone', '--quiet', '--shared', str(ROOT), str(repo)], check=True)
            # A source tree may be under development while its archive remains at HEAD.
            shutil.copyfile(ROOT / COMPATIBILITY_FILE, repo / COMPATIBILITY_FILE)
            git(repo, 'config', 'user.name', 'Fixture')
            git(repo, 'config', 'user.email', 'fixture@example.com')

            def commit(paths):
                git(repo, 'add', '-f', '--', *paths)
                git(repo, 'commit', '-m', 'test fixture')
            result = verify_results(repo)
            self.assertEqual(result['historical_crlf_files'], 251)
            self.assertEqual(result['affected_historical_bundles'], 87)
            self.assertGreaterEqual(result['files'], 744)
            self.assertEqual(result['exact'], result['files'] - 251)
            self.assertGreaterEqual(result['bundles'], 95)

            ledger = json.loads((repo / COMPATIBILITY_FILE).read_bytes())
            name, entry = next((name, m) for name, m in ledger['manifests'].items() if m['crlf_exceptions'])
            source = Path(name).parent / next(iter(entry['crlf_exceptions']))
            extra = repo / Path(name).parent / 'extra.txt'
            extra.write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError, 'Checkout file inventory differs'):
                verify_results(repo)
            extra.unlink()
            (repo / source).write_bytes((repo / source).read_bytes() + b'altered\n')
            with self.assertRaisesRegex(ValueError, 'Checkout bytes differ'):
                verify_results(repo)
            commit([source])
            with self.assertRaisesRegex(ValueError, 'differs from the recorded compatibility entry'):
                verify_results(repo)
            git(repo, 'revert', '--no-edit', 'HEAD')
            old_manifest = repo / name
            old_manifest.write_bytes(old_manifest.read_bytes() + b'\n')
            commit([name])
            with self.assertRaisesRegex(ValueError, 'Historical manifest differs'):
                verify_results(repo)
            git(repo, 'revert', '--no-edit', 'HEAD')

            fresh = Path('docs/results/model-offloading/new-publication')
            (repo / fresh).mkdir(parents=True)
            readme = fresh / 'README.md'
            (repo / readme).write_bytes(b'new report\n')
            bad = {'files': {readme.as_posix(): hashlib.sha256(b'new report\r\n').hexdigest()}}
            bad['report_fingerprint'] = digest(bad)
            (repo / fresh / 'manifest.json').write_bytes(json.dumps(bad).encode())
            commit([fresh])
            with self.assertRaisesRegex(ValueError, 'SHA-256 differs from the manifest'):
                verify_results(repo)
            (repo / COMPATIBILITY_FILE).write_bytes(json.dumps(ledger).encode())
            with self.assertRaisesRegex(ValueError, 'compatibility map has changed'):
                verify_results(repo)


class ForkPolicyTests(legal_fixtures.Base):
    def test_fork_preparation_preserves_legal_publication_gates(self):
        campaign = self.smoke()
        report = self.report(campaign)
        with patch('llm_eval.reporting.publish._prepare_fork', side_effect=AssertionError('prepared restricted data')):
            with self.assertRaisesRegex(ValueError, 'not_authorized'):
                publish_report(report, ROOT, prepare_fork='contributor/llm-eval')
            self.authorize(campaign)
            with self.assertRaisesRegex(ValueError, 'restricted projection'):
                publish_report(report, ROOT, prepare_fork='contributor/llm-eval')
