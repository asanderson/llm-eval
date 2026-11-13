"""Package B of issue 45: immutable matter packets, offline ingestion and the gated dataset import.

Every fixture here is original and fictional. The adapter fixtures are FORMAT FIXTURES: they imitate the assumed layout of
an upstream benchmark so the converter can be tested offline; they are not the dataset and contain none of its text.
"""
import copy
import datetime
import email
import email.policy
from email.message import EmailMessage
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from llm_eval.common import read_json, sha256_file
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import benchmarks, contracts, fixture, ingest

ROOT = Path(__file__).resolve().parents[1]
X = ROOT / 'experiments/legal-benchmark'
SMOKE = X / 'workloads/original-smoke'
PACKETS = X / 'workloads/original-packets'
INGEST = 'llm_eval.experiments.legal_benchmark.ingest'
NONCE = 'ab' * 16


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ingest._dump(value))


def message(subject='Dock log', body='The ferry left the north dock at noon.\n', sender='dock.clerk@veld.example', headers=None, html=None,
            date='Mon, 05 May 2025 10:00:00 +0000'):
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = 'screening.desk@veld.example'
    if subject is not None:
        msg['Subject'] = subject
    if date is not None:
        msg['Date'] = date
    for name, value in (headers or {}).items():
        msg[name] = value
    if body is not None:
        msg.set_content(body)
        if html is not None:
            msg.add_alternative(html, subtype='html')
    else:
        msg.set_content(html, subtype='html')
    return msg


def relock(directory, drop=(), **changes):
    """Rewrite the lock of an ingested or imported suite after an edit made on purpose, optionally without some entries."""
    directory = Path(directory)
    lock = read_json(directory / 'suite.lock.json')
    manifests = {e['purpose']: e['path'] for e in lock['source_files'] if e['purpose'] != 'source' and e['purpose'] not in drop}
    sources = [e['path'] for e in lock['source_files'] if e['purpose'] == 'source' and e['path'] not in drop]
    new = contracts.make_lock(directory, benchmark_id=lock['benchmark_id'], revision=lock['revision'], split_id=lock['split_id'],
                              data_class=lock['data_class'], jurisdiction_profile=lock['jurisdiction_profile'], manifests=manifests, sources=sources)
    new.update(changes)
    dump(directory / 'suite.lock.json', new)
    return directory / 'suite.lock.json'


def edit(path, change):
    value = read_json(path)
    change(value)
    dump(path, value)


AUTHORITY = {'authority_id': 'vdo-2-1', 'version': '2022', 'citation': 'Veld Dock Ordinance s2.1', 'title': 'Berthing a ferry at a closed dock',
             'issuer': 'Assembly of Veld (fictional)', 'authority_type': 'offence', 'venues': ['veld-harbor'], 'effective_from': '2022-01-01',
             'effective_to': None, 'status': 'in_force', 'pinpoint': 's2.1',
             'elements': [{'element_id': 'berthed', 'description': 'Evidence that a ferry berthed.', 'terms': ['berthed']}],
             'weight': 'controlling', 'snapshot': {'id': 'veld-gazette-test', 'published': '2025-01-01'}, 'status_as_of': '2025-01-01'}


class Packet:
    """A small original, fictional collection in a temporary directory: one family of two matters."""

    def __init__(self, test, data_class='public-synthetic'):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / 'suite'
        self.dir.mkdir()
        self.data_class = data_class
        self.matters = [{'matter_id': m, 'family_id': 't1-dock', 'operative_date': '2025-04-01', 'venue': 'veld-harbor', 'posture': 'screening',
                         'question': 'Does berthing the ferry at the closed north dock support a charge?', 'output_schema': 'candidate-output-v1'}
                        for m in ('t1-dock-a', 't1-dock-b')]
        self.files, self.rules = [], []

    def add(self, path, data, source_set='candidate', excluded=None, **entry):
        target = self.dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        self.files.append({'path': path, **entry})
        rule = {'path': path, 'source_set': source_set}
        if excluded is not None:
            rule['excluded_matters'] = excluded
        self.rules.append(rule)
        return self

    def evidence(self, path, data, matter='t1-dock-a', kind='report', **rule):
        return self.add(path, data, namespace='evidence', matter_id=matter, kind=kind, **rule)

    def write(self):
        dump(self.dir / 'collection.json', {'schema_version': 1, 'data_class': self.data_class, 'jurisdiction_profile': 'veld-fictional-v1',
                                            'venues': ['veld-harbor'], 'matters': self.matters, 'files': self.files})
        dump(self.dir / 'visibility.json', {'schema_version': 1, 'rules': self.rules})

    def ingest(self, root=None):
        self.write()
        return ingest.ingest_collection(self.dir / 'collection.json', self.dir / 'visibility.json', self.dir, root=root)

    def rubric(self):
        dump(self.dir / 'rubric.json', {
            'schema_version': 1, 'data_class': self.data_class, 'jurisdiction_profile': 'veld-fictional-v1', 'source_set': 'grader',
            'rubric_version': 'test-rubric-1', 'matters': [
                {'matter_id': m['matter_id'], 'scenario': 'fixture', 'variant': 'base', 'recommendation': 'decline', 'controlling_authority': None,
                 'ineligible_versions': [], 'elements': {}, 'conflict_elements': [], 'missing_elements': [], 'established_exemptions': [],
                 'injection_span_ids': [], 'evidence_spans': {}, 'exemption_spans': {},
                 'reference_passages': {'evidence': [], 'authorities': [], 'adverse': []}} for m in self.matters]})

    def lock(self):
        self.ingest()
        self.rubric()
        return ingest.lock_suite(self.dir, benchmark_id='legal-test-packets', revision='2026-11-12.1', split_id='test')

    def json(self, name):
        return read_json(self.dir / name)


def basic(test):
    return (Packet(test).evidence('raw/a/report.txt', 'Dock report.\n\nThe ferry berthed at the north dock after it closed.\n')
            .evidence('raw/b/report.txt', 'Dock report.\n\nThe ferry waited outside the north dock.\n', matter='t1-dock-b'))


class TextIngestTests(unittest.TestCase):
    def test_text_is_split_into_stable_anchored_spans(self):
        long = ('The ferry Lark berthed at the north dock. ' * 3).strip()
        data = ('\ufeffDock report.\r\n\r\nFirst line of the second paragraph.\r\nIts second line.\r\n\r\n' + long + '\n').encode('utf-8')
        with patch.dict(ingest.LIMITS, {'max_span_chars': 60}):
            sources, entries = ingest.ingest_bytes(data, name='raw/report.txt', namespace='evidence', kind='report', matter_id='t1-dock-a')
            again = ingest.ingest_bytes(data, name='raw/report.txt', namespace='evidence', kind='report', matter_id='t1-dock-a')
        self.assertEqual((sources, entries), again)
        self.assertEqual(len(sources), 1)
        record = sources[0]
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(record['source_id'], 's-' + hashlib.sha256(('evidence\0t1-dock-a\0' + digest + '\0').encode()).hexdigest()[:16])
        self.assertEqual((record['original_sha256'], record['original_bytes'], record['media_type']), (digest, len(data), 'text/plain'))
        self.assertEqual(record['parse'], {'status': 'ok', 'confidence': 1.0, 'missing_pages': [], 'ocr_required_pages': [], 'reason_codes': []})
        normalised = data.decode('utf-8')[1:].replace('\r\n', '\n')
        texts = [span['text'] for span in record['spans']]
        self.assertEqual(texts, ['Dock report.', 'First line of the second paragraph.\nIts second line.',
                                 'The ferry Lark berthed at the north dock.', 'The ferry Lark berthed at the north dock.',
                                 'The ferry Lark berthed at the north dock.'])
        for number, span in enumerate(record['spans'], 1):
            locator = span['locator']
            self.assertEqual((span['span_id'], locator['kind'], locator['paragraph']), (f"{record['source_id']}#{number}", 'text', number))
            self.assertEqual(normalised[locator['start']:locator['end']], span['text'])
            self.assertEqual(span['text_sha256'], contracts.text_digest(span['text']))
        self.assertEqual(entries, [{'path': 'raw/report.txt', 'part': '', 'sha256': digest, 'bytes': len(data), 'media_type': 'text/plain',
                                    'status': 'ok', 'reason_codes': [], 'duplicate_of': None}])
        # The id depends on namespace, owning matter and digest only: not on the name.
        same = ingest.ingest_bytes(data, name='other/name.txt', namespace='evidence', kind='statement', matter_id='t1-dock-a')[0][0]
        self.assertEqual(same['source_id'], record['source_id'])
        ids = {ingest.source_id('evidence', digest, '', 't1-dock-a'), ingest.source_id('evidence', digest, '', 't1-dock-b'),
               ingest.source_id('template', digest), ingest.source_id('evidence', 'f' * 64, '', 't1-dock-a')}
        self.assertEqual(len(ids), 4)
        # Two paired matters with a byte-identical file: two sources with different ids, and the manifest loads.
        text = 'Dock report.\n\nThe ferry berthed at the north dock after it closed.\n'
        packet = Packet(self).evidence('raw/a/report.txt', text).evidence('raw/b/report.txt', text, matter='t1-dock-b')
        suite = contracts.load_suite(packet.lock())
        a, b = (m['sources'][0] for m in suite['matters']['matters'])
        self.assertEqual(a['original_sha256'], b['original_sha256'])
        self.assertNotEqual(a['source_id'], b['source_id'])
        self.assertEqual([s['text'] for s in a['spans']], [s['text'] for s in b['spans']])

    def test_invalid_utf8_oversize_and_unknown_types_are_recorded_not_guessed(self):
        def one(data, name):
            return ingest.ingest_bytes(data, name=name, namespace='evidence', kind='report', matter_id='t1-dock-a')
        sources, entries = one(b'The dock log \xff\xfe is damaged.\n', 'raw/log.txt')
        self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'corrupt', ['invalid_utf8']))
        with patch.dict(ingest.LIMITS, {'max_file_bytes': 10}):
            sources, entries = one(b'A dock report that is longer than ten bytes.\n', 'raw/big.txt')
        self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', ['too_large']))
        for name, reason in (('raw/bundle.zip', 'archive_not_expanded'), ('raw/bundle.tar.gz', 'archive_not_expanded'),
                             ('raw/scan.tiff', 'unknown_type'), ('raw/noextension', 'unknown_type')):
            with self.subTest(name=name):
                sources, entries = one(b'PK\x03\x04 not expanded', name)
                self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', [reason]))
        sources, entries = one(b'\n\n  \n', 'raw/empty.txt')
        self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', ['no_text']))
        sources, entries = one('A bell\x07 rang at the dock.\n'.encode(), 'raw/bell.txt')
        self.assertEqual(sources[0]['spans'][0]['text'], 'A bell\ufffd rang at the dock.')
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('ok', ['control_characters_replaced']))

    def test_package_sources_spell_invisible_characters_as_escapes(self):
        for path in [ROOT / 'src/llm_eval/experiments/legal_benchmark' / name for name in ('ingest.py', 'benchmarks.py', 'contracts.py')] + \
                [Path(__file__)]:
            with self.subTest(path=path.name):
                self.assertEqual([c for c in path.read_text(encoding='utf-8') if ord(c) > 127], [])

    def test_identical_authority_versions_both_reach_the_corpus(self):
        text = 'A master who berths a ferry at a closed dock commits an offence.\n'
        older = {**AUTHORITY, 'effective_to': '2024-01-01', 'status': 'superseded'}
        newer = {**AUTHORITY, 'version': '2024', 'effective_from': '2024-01-01'}
        packet = basic(self).add('raw/law-2022.txt', text, namespace='authority', authority=older)
        packet.add('raw/law-2024.txt', text, namespace='authority', authority=newer)
        report = packet.ingest()
        self.assertEqual([(e['path'], e['status']) for e in report['files'][-2:]], [('raw/law-2022.txt', 'ok'), ('raw/law-2024.txt', 'ok')])
        corpus = contracts.load_suite(packet.lock())['corpus']
        self.assertEqual([(a['authority_id'], a['version']) for a in corpus['authorities']], [('vdo-2-1', '2022'), ('vdo-2-1', '2024')])
        self.assertEqual(len({a['original_sha256'] for a in corpus['authorities']}), 1)
        # The same authority version collected twice (here with different metadata and identical text) is refused.
        packet = basic(self).add('raw/law-a.txt', text, namespace='authority', authority=older)
        packet.add('raw/law-b.txt', text, namespace='authority', authority={**older, 'effective_from': '2023-01-01'})
        with self.assertRaisesRegex(ValueError, 'Duplicate authority version in the collection: vdo-2-1@2022'):
            packet.ingest()


class EmailIngestTests(unittest.TestCase):
    def ingest(self, msg, roles=None, matter='t1-dock-a'):
        data = msg if isinstance(msg, bytes) else msg.as_bytes()
        return ingest.ingest_bytes(data, name='raw/thread.eml', namespace='evidence', kind='message', matter_id=matter, sender_roles=roles)

    def test_nested_mime_and_attachments_keep_parent_anchors(self):
        inner = message('Inner note', 'The inner note names the north berth.\n', headers={'Message-ID': '<inner@veld.example>'})
        inner.add_attachment(b'Tally sheet of the north berth.\n', maintype='text', subtype='plain', filename='../../tally.txt')
        outer = message('Outer cover', 'See the attached note from the berth office.\n', headers={'Message-ID': '<outer@veld.example>'})
        outer.add_attachment(inner)
        sources, entries = self.ingest(outer)
        self.assertEqual([e['part'] for e in entries], ['', '3', '3.3'])
        self.assertEqual([e['status'] for e in entries], ['ok', 'ok', 'ok'])
        root, nested, tally = sources
        self.assertEqual((root['parent_source_id'], root['attachments']), (None, [nested['source_id']]))
        self.assertEqual((nested['parent_source_id'], nested['attachments'], nested['kind'], nested['media_type']),
                         (root['source_id'], [tally['source_id']], 'message', 'message/rfc822'))
        self.assertEqual((tally['parent_source_id'], tally['kind'], tally['media_type']), (nested['source_id'], 'attachment', 'text/plain'))
        self.assertEqual(tally['original_sha256'], hashlib.sha256(b'Tally sheet of the north berth.\n').hexdigest())
        self.assertEqual(tally['spans'][0]['text'], 'Tally sheet of the north berth.')
        self.assertNotIn('tally', json.dumps(sources).replace('Tally sheet', ''))      # the untrusted file name is not stored
        self.assertEqual([s['locator'] for s in root['spans']],
                         [{'kind': 'email-body', 'part': 'subject', 'start': 0, 'end': 11}, {'kind': 'email-body', 'part': '2', 'start': 0, 'end': 44}])
        self.assertEqual(nested['email']['message_id'], '<inner@veld.example>')
        with patch.dict(ingest.LIMITS, {'max_attachment_depth': 1}):
            sources, entries = self.ingest(outer)
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[1]['attachments'], [])
        self.assertEqual((entries[2]['part'], entries[2]['status'], entries[2]['reason_codes']), ('3.3', 'unsupported', ['nesting_too_deep']))

    def test_bad_dates_are_null_with_a_reason_code(self):
        cases = [(None, None, 'bad_date'), ('not a date at all', None, 'bad_date'),
                 ('Fri, 02 May 2025 09:15:00', None, 'date_without_zone'), ('Fri, 02 May 2025 09:15:00 -0000', None, 'date_without_zone'),
                 ('Fri, 02 May 2025 09:15:00 +0200', '2025-05-02T07:15:00+00:00', None),
                 # a year that is not written with four digits, or lies before 1900, is never given a century
                 ('Fri, 02 May 25 09:15:00 +0200', None, 'bad_date'), ('Fri, 02 May 49 09:15:00 +0000', None, 'bad_date'),
                 ('Mon, 01 Jan 0001 00:00:00 +0000', None, 'bad_date'), ('Sat, 01 Jan 1898 00:00:00 +0000', None, 'bad_date'),
                 # a value that overflows during the conversion is a bad date, not a dropped email
                 ('Fri, 31 Dec 9999 23:00:00 -1200', None, 'bad_date'),
                 # the year token is the last number of the date whatever the order or separator, and has exactly four digits
                 ('Fri, 02-May-25 09:15:00 +0000', None, 'bad_date'), ('Fri, 02 May 02025 09:15:00 +0000', None, 'bad_date'),
                 ('Fri, May 02 2025 09:15:00 +0200', '2025-05-02T07:15:00+00:00', None),
                 ('Fri, 02-May-2025 09:15:00 -0100', '2025-05-02T10:15:00+00:00', None),
                 ('Fri, 02 May 2025 09:15:00 +0200 (CEST)', '2025-05-02T07:15:00+00:00', None)]

        def run():
            results = []
            for header, _, _ in cases:
                data = b'From: dock.clerk@veld.example\nSubject: Dock log\n' + (b'' if header is None else b'Date: ' + header.encode() + b'\n')
                sources, entries = self.ingest(data + b'\nThe ferry left the north dock at noon.\n')
                results.append((sources[0]['email']['date'] if sources else 'no record', entries[0]['reason_codes'], entries[0]['status']))
            return results
        expected = [(date, [reason] if reason else [], 'ok') for _, date, reason in cases]
        self.assertEqual(run(), expected)
        # The result does not depend on the time zone of the host: a value without a zone is never converted. The host zone is
        # changed where the platform allows it; on every platform a naive value refuses conversion outright.
        with patch.dict(os.environ, {'TZ': 'Pacific/Kiritimati'}):
            if hasattr(time, 'tzset'):
                time.tzset()
            self.assertEqual(run(), expected)
        if hasattr(time, 'tzset'):
            time.tzset()

        class Naive(datetime.datetime):
            def astimezone(self, tz=None):
                raise AssertionError('a value without a zone was converted')
        with patch('email.utils.parsedate_to_datetime', return_value=Naive(2025, 5, 2, 9, 15)):
            sources, entries = self.ingest(message())
        self.assertEqual((sources[0]['email']['date'], entries[0]['reason_codes']), (None, ['date_without_zone']))

    def test_oversized_headers_are_refused_before_parsing(self):
        self.assertEqual((ingest.LIMITS['max_header_bytes'], ingest.LIMITS['max_header_line_bytes']), (64 * 1024, 8 * 1024))
        body = b'\r\n\r\nThe ferry left the north dock at noon.\r\n'
        cases = {'two-megabyte subject': b'Subject: ' + b'w ' * 1_000_000 + body,
                 'hundred thousand senders': b'From: ' + b'a@b.example, ' * 100_000 + b'\r\nSubject: s' + body,
                 'one header above 8 KiB': b'Subject: s\r\nX-Note: ' + b'n' * (9 * 1024) + body,
                 'folded header above 8 KiB': b'Subject: s\r\nX-Note: n' + b'\r\n n' * 5000 + body,
                 'block above 64 KiB': b'Subject: s\r\n' + b''.join(b'X-Note-%d: %s\r\n' % (i, b'n' * 1000) for i in range(70)) + body[2:]}
        for name, data in cases.items():
            with self.subTest(name):
                sources, entries = self.ingest(data)
                self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', ['header_too_large']))
        inner = b'From: a@b.example\r\nSubject: ' + b'w ' * 1_000_000 + body
        outer = (b'From: dock.clerk@veld.example\r\nSubject: Cover\r\nDate: Mon, 05 May 2025 10:00:00 +0000\r\nMIME-Version: 1.0\r\n'
                 b'Content-Type: multipart/mixed; boundary="veld"\r\n\r\n--veld\r\nContent-Type: text/plain\r\n\r\nSee the attached message.\r\n'
                 b'--veld\r\nContent-Type: message/rfc822\r\n\r\n' + inner + b'\r\n--veld--\r\n')
        sources, entries = self.ingest(outer)
        self.assertEqual(len(sources), 1)
        self.assertEqual([(e['part'], e['status'], e['reason_codes']) for e in entries],
                         [('', 'ok', []), ('3', 'unsupported', ['header_too_large'])])
        sources, entries = self.ingest(b'Subject: s\r\nX-Note: ' + b'n' * 8000 + body)      # below both limits
        self.assertEqual(entries[0]['status'], 'ok')

    def test_part_headers_are_limited_before_structured_parsing(self):
        real = email.message_from_bytes

        def guarded(data, *args, **kwargs):      # the structured (default-policy) parse must never see these inputs whole
            if kwargs.get('policy') is email.policy.default and len(data) > 200_000:
                raise AssertionError('structured parse of an oversized message')
            return real(data, *args, **kwargs)

        def mail(content_type, body):
            return (b'From: a@x.example\r\nSubject: S\r\nDate: Fri, 02 May 2025 09:15:00 +0200\r\nMIME-Version: 1.0\r\n'
                    b'Content-Type: ' + content_type + b'\r\n\r\n' + body)
        params = b'a=b; ' * 200_000      # reviewer probe p9: a 976 KiB Content-Type of a MIME part
        flat = mail(b'multipart/mixed; boundary="B"', b'--B\r\nContent-Type: text/plain; ' + params + b'\r\n\r\nx\r\n--B--\r\n')
        nested = mail(b'multipart/mixed; boundary="B"', b'--B\r\nContent-Type: multipart/alternative; boundary="C"; ' + params +
                      b'\r\n\r\n--C\r\nContent-Type: text/plain\r\n\r\nx\r\n--C--\r\n--B--\r\n')
        many = mail(b'multipart/mixed; boundary="B"', b''.join(b'--B\r\nContent-Type: text/plain\r\n\r\nbody %d.\r\n' % i for i in range(20_000))
                    + b'--B--\r\n')
        with patch('email.message_from_bytes', guarded):
            for name, data in (('part Content-Type', flat), ('nested multipart Content-Type', nested)):
                with self.subTest(name):
                    sources, entries = self.ingest(data)
                    self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', ['header_too_large']))
            sources, entries = self.ingest(many)
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('partial', ['too_many_parts']))
        self.assertEqual(len(sources), 1)
        self.assertEqual(len(sources[0]['spans']), ingest.LIMITS['max_parts'])      # subject + the text parts walked (all but the root)

    def test_an_email_without_text_still_reports_its_attachments(self):
        msg = EmailMessage()
        msg['From'] = 'dock.clerk@veld.example'
        msg['Date'] = 'Mon, 05 May 2025 10:00:00 +0000'
        msg.add_attachment(b'Berth plan of the north dock.\n', maintype='text', subtype='plain', filename='plan.txt')
        msg.add_attachment(b'PK fixture', maintype='application', subtype='zip', filename='photos.zip')
        sources, entries = self.ingest(msg)
        self.assertEqual([(e['status'], e['reason_codes']) for e in entries],
                         [('unsupported', ['no_text']), ('ok', []), ('unsupported', ['archive_not_expanded'])])
        self.assertEqual([s['spans'][0]['text'] for s in sources], ['Berth plan of the north dock.'])

    def test_parts_per_email_are_capped(self):
        self.assertEqual(ingest.LIMITS['max_parts'], 500)
        parts = b''.join(b'--B\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename="f%d.txt"\r\n\r\npart %d unique text.\r\n'
                         % (i, i) for i in range(600))
        data = (b'From: dock.clerk@veld.example\r\nSubject: Many\r\nDate: Mon, 05 May 2025 10:00:00 +0000\r\nMIME-Version: 1.0\r\n'
                b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\nMany parts follow.\r\n' + parts + b'--B--\r\n')
        sources, entries = self.ingest(data)
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('partial', ['too_many_parts']))
        self.assertLessEqual(len(sources), 500)
        self.assertLessEqual(len(entries), 500)

    def test_html_elements_are_separated_and_templates_dropped(self):
        markup = '<html><head><title>Berth notice</title></head><body><noscript>Enable scripts</noscript><template>Hidden template</template>' \
                 '<p>The berth is closed.</p></body></html>'
        sources, _ = self.ingest(message('Html', None, html=markup))
        self.assertEqual([s['text'] for s in sources[0]['spans']], ['Html', 'Berth notice', 'Enable scripts', 'The berth is closed.'])

    def test_repeated_attachments_yield_one_source(self):
        msg = message('Two copies', 'Both copies of the berth plan are attached.\n')
        for _ in range(2):
            msg.add_attachment(b'Berth plan of the north dock.\n', maintype='text', subtype='plain', filename='plan.txt')
        sources, entries = self.ingest(msg)
        self.assertEqual(len(sources), 2)
        child = sources[1]['source_id']
        self.assertEqual(sources[0]['attachments'], [child])
        self.assertEqual([(e['status'], e['duplicate_of']) for e in entries], [('ok', None), ('ok', None), ('duplicate', child)])
        # Across files of one matter: the same attachment bytes on two emails give one record listed in both parents.
        first = message('First', 'The berth plan is attached.\n', headers={'Message-ID': '<first@veld.example>'})
        second = message('Second', 'The berth plan is attached again.\n', headers={'Message-ID': '<second@veld.example>'})
        for msg in (first, second):
            msg.add_attachment(b'Berth plan of the north dock.\n', maintype='text', subtype='plain', filename='plan.txt')
        packet = Packet(self).evidence('raw/first.eml', first.as_bytes(), kind='message').evidence('raw/second.eml', second.as_bytes(), kind='message')
        packet.evidence('raw/copy-of-first.eml', first.as_bytes(), kind='message')
        packet.evidence('raw/b.txt', 'The other matter has its own report.\n', matter='t1-dock-b')
        report = packet.ingest()
        sources = packet.json('matters.json')['matters'][0]['sources']
        children = [s for s in sources if s['parent_source_id'] is not None]
        self.assertEqual(len(children), 1)
        self.assertEqual([s['attachments'] for s in sources if s['parent_source_id'] is None], [[children[0]['source_id']]] * 2)
        statuses = [(e['path'], e['part'], e['status']) for e in report['files']]
        self.assertEqual(statuses[:5], [('raw/first.eml', '', 'ok'), ('raw/first.eml', '3', 'ok'), ('raw/second.eml', '', 'ok'),
                                        ('raw/second.eml', '3', 'duplicate'), ('raw/copy-of-first.eml', '', 'duplicate')])
        contracts.load_suite(packet.lock())

    def test_bad_charset_part_is_skipped_and_reported(self):
        data = (b'From: dock.clerk@veld.example\nSubject: Charset check\nDate: Mon, 05 May 2025 10:00:00 +0000\n'
                b'Message-ID: <cs@veld.example>\nMIME-Version: 1.0\n'
                b'Content-Type: multipart/mixed; boundary="veld"\n\n'
                b'--veld\nContent-Type: text/plain; charset="x-unknown-veld"\n\nA part in a charset nobody knows.\n'
                b'--veld\nContent-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\nBroken \xff\xfe bytes.\n'
                b'--veld\nContent-Type: text/plain; charset="utf-8"\n\nThe readable part names the north dock.\n--veld--\n')
        sources, entries = self.ingest(data)
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('partial', ['bad_charset']))
        self.assertEqual(sources[0]['parse']['status'], 'partial')
        self.assertEqual([s['text'] for s in sources[0]['spans']], ['Charset check', 'The readable part names the north dock.'])
        self.assertEqual(sources[0]['spans'][1]['locator']['part'], '4')
        self.assertNotIn('\ufffd', json.dumps(sources, ensure_ascii=False))      # no guessed or replaced decoding

    def test_quoted_text_is_separated_and_thread_ids_are_stable(self):
        body = ('The dock clerk confirms that the ferry left at noon.\n\n'
                '> Did the ferry leave on time?\n> Please confirm.\n\n'
                'A closing line from the clerk.\n'
                '-----Original Message-----\nFrom: Screening Desk\nThe ferry schedule was posted on the gate.\n')
        first = message('Ferry times', 'Did the ferry leave on time?\n', sender='Desk <Screening.Desk@veld.example>',
                        headers={'Message-ID': '<m1@veld.example>'})
        reply = message('Re: Ferry times', body, headers={'Message-ID': '<m2@veld.example>', 'In-Reply-To': '<m1@veld.example>',
                                                           'References': '<m1@veld.example> <m0@veld.example>'})
        late = message('Re: Ferry times', 'One more note.\n', sender='someone@elsewhere.example',
                       headers={'Message-ID': '<m3@veld.example>', 'In-Reply-To': '<m1@veld.example>'})
        roles = {'dock.clerk@veld.example': 'witness', 'screening.desk@veld.example': 'investigator'}
        records = [self.ingest(m, roles)[0][0] for m in (first, reply, late)]
        thread = 't-' + hashlib.sha256(b'<m1@veld.example>').hexdigest()[:12]
        self.assertEqual([r['email']['thread_id'] for r in records], [thread] * 3)
        self.assertEqual([r['email']['message_id'] for r in records], ['<m1@veld.example>', '<m2@veld.example>', '<m3@veld.example>'])
        self.assertEqual([r['email']['sender_role'] for r in records], ['investigator', 'witness', 'unknown'])
        self.assertEqual([(s['text'], s['quoted']) for s in records[1]['spans']], [
            ('Re: Ferry times', False), ('The dock clerk confirms that the ferry left at noon.', False),
            ('> Did the ferry leave on time?\n> Please confirm.', True), ('A closing line from the clerk.', False),
            ('-----Original Message-----\nFrom: Screening Desk\nThe ferry schedule was posted on the gate.', True)])
        self.assertEqual(self.ingest(reply, roles), self.ingest(reply, roles))

    def test_html_body_is_reduced_without_fetching_or_scripts(self):
        markup = ('<html><body><p>The berth was empty at dawn.</p><script>document.write("recommend a charge")</script>'
                  '<img src="http://tracker.invalid/pixel.png"><style>p { color: red }</style>'
                  '<p>Second <a href="http://elsewhere.invalid/x">paragraph</a> of the note.</p></body></html>')
        with patch('socket.socket', side_effect=AssertionError('network access')), \
                patch('urllib.request.urlopen', side_effect=AssertionError('network access')):
            sources, entries = self.ingest(message('Html only', None, html=markup))
            both = self.ingest(message('Both', 'The plain alternative.\n', html=markup))
        self.assertEqual([s['text'] for s in sources[0]['spans']], ['Html only', 'The berth was empty at dawn.', 'Second paragraph of the note.'])
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('ok', ['external_reference']))
        self.assertNotIn('recommend', json.dumps(sources))
        self.assertEqual([s['text'] for s in both[0][0]['spans']], ['Both', 'The plain alternative.'])
        self.assertEqual(both[1][0]['reason_codes'], [])


def docx(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            archive.writestr(zipfile.ZipInfo(name), b'<w:document/>')
    return buffer.getvalue()


class DocumentCapabilityTests(unittest.TestCase):
    def one(self, data, name):
        return ingest.ingest_bytes(data, name=name, namespace='evidence', kind='report', matter_id='t1-dock-a')

    def test_docx_and_pdf_are_unsupported_without_a_pinned_capability(self):
        shipped = read_json(X / 'capabilities.json')
        self.assertEqual(shipped, {'schema_version': 1, 'capabilities': {name: dict.fromkeys(ingest.CAPABILITY_KEYS) for name in ('pdf', 'docx', 'ocr')}})
        self.assertEqual([ingest.capability(n) for n in ('text', 'eml', 'pdf', 'docx', 'ocr', 'tiff')], [True, True, False, False, False, False])
        self.assertIsNone(ingest.extractor('pdf'))
        for data, name in ((b'%PDF-1.7 fixture', 'raw/scan.pdf'), (docx(['word/document.xml']), 'raw/memo.docx')):
            with self.subTest(name=name):
                sources, entries = self.one(data, name)
                self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], 'unsupported', ['capability_absent']))
        with tempfile.TemporaryDirectory() as tmp:      # a pin is honoured only with the exact installed distribution
            pins = {'pdf': {'module': 'json', 'distribution': 'no-such-distribution-veld', 'version': '1.0', 'callable': 'loads'},
                    'docx': {'module': 'no_such_module_veld', 'distribution': 'no-such-distribution-veld', 'version': '1.0', 'callable': 'x'}}
            dump(Path(tmp) / ingest.CAPABILITIES, {'schema_version': 1, 'capabilities': pins})
            self.assertEqual((ingest.capability('pdf', tmp), ingest.capability('docx', tmp)), (False, False))
            self.assertIsNone(ingest.extractor('pdf', tmp))

    def test_encrypted_and_corrupt_documents_are_recorded(self):
        for status in ('encrypted', 'corrupt'):
            with self.subTest(status=status):
                fake = Mock(return_value={'status': status, 'pages': 0, 'units': []})
                with patch(INGEST + '.extractor', return_value=fake):
                    sources, entries = self.one(b'%PDF-1.7 fixture', 'raw/locked.pdf')
                    self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], status, [status]))
                    packet = basic(self).evidence('raw/locked.pdf', b'%PDF-1.7 fixture ' + status.encode())
                    report = packet.ingest()
                self.assertEqual(report['files'][-1]['status'], status)
                packet.rubric()
                with self.assertRaisesRegex(ValueError, 'Suite has unparsed files: raw/locked.pdf'):
                    ingest.lock_suite(packet.dir, benchmark_id='legal-test', revision='1', split_id='test')
                self.assertFalse((packet.dir / 'suite.lock.json').exists())

    def test_missing_and_ocr_only_pages_are_recorded_and_block_the_lock(self):
        result = {'status': 'ok', 'pages': 3, 'units': [
            {'page': 1, 'text': 'Page one of the dock survey.', 'bbox': [0, 0, 100, 20], 'confidence': 0.9},
            {'page': 2, 'text': None, 'bbox': None, 'confidence': None}]}
        with patch(INGEST + '.extractor', return_value=Mock(return_value=result)):
            sources, entries = self.one(b'%PDF-1.7 survey', 'raw/survey.pdf')
            packet = basic(self).evidence('raw/survey.pdf', b'%PDF-1.7 survey')
            packet.ingest()
        self.assertEqual(sources[0]['parse'], {'status': 'partial', 'confidence': 0.9, 'missing_pages': [3], 'ocr_required_pages': [2],
                                               'reason_codes': ['missing_pages', 'ocr_required']})
        self.assertEqual([(s['text'], s['locator']) for s in sources[0]['spans']],
                         [('Page one of the dock survey.', {'kind': 'pdf-page', 'page': 1, 'bbox': [0, 0, 100, 20]})])
        self.assertEqual((entries[0]['status'], entries[0]['reason_codes']), ('partial', ['missing_pages', 'ocr_required']))
        packet.rubric()
        with self.assertRaisesRegex(ValueError, 'Suite has unparsed files: raw/survey.pdf'):
            ingest.lock_suite(packet.dir, benchmark_id='legal-test', revision='1', split_id='test')
        # A partial source that reached a lock by hand is still an unresolved anchor.
        packet = basic(self)
        lock = packet.lock()
        edit(packet.dir / 'matters.json', lambda m: m['matters'][0]['sources'][0]['parse'].update(status='partial', ocr_required_pages=[2]))
        with self.assertRaisesRegex(ValueError, 'Unresolved anchor: ' + read_json(packet.dir / 'matters.json')['matters'][0]['sources'][0]['source_id']):
            contracts.load_suite(relock(packet.dir))
        self.assertTrue(lock.exists())

    def test_redlines_and_comments_are_preserved_with_known_expected_extraction(self):
        units = [{'section': 1, 'paragraph': 1, 'text': 'Clause one stays as agreed.', 'revision': None, 'comments': []},
                 {'section': 1, 'paragraph': 2, 'text': 'Clause two is newly inserted.', 'revision': 'inserted', 'comments': []},
                 {'section': 1, 'paragraph': 3, 'text': 'Clause three was struck out.', 'revision': 'deleted', 'comments': []},
                 {'section': 2, 'paragraph': 1, 'text': 'Clause four carries a note.', 'revision': None, 'comments': ['Check the berth date.']},
                 {'section': 2, 'paragraph': 2, 'text': '   ', 'revision': None, 'comments': []}]
        data = docx(['[Content_Types].xml', 'word/document.xml', 'word/comments.xml'])
        with patch(INGEST + '.extractor', return_value=Mock(return_value={'status': 'ok', 'units': units})):
            sources, entries = self.one(data, 'raw/lease.docx')
        sid = sources[0]['source_id']

        def span(n, text, section, paragraph, **extra):
            return {'span_id': f'{sid}#{n}', 'text': text, 'text_sha256': contracts.text_digest(text),
                    'locator': {'kind': 'docx-paragraph', 'section': section, 'paragraph': paragraph}, **extra}
        self.assertEqual(sources[0]['spans'], [span(1, 'Clause one stays as agreed.', 1, 1),
                                               span(2, 'Clause two is newly inserted.', 1, 2, revision='inserted'),
                                               span(3, 'Clause three was struck out.', 1, 3, revision='deleted'),
                                               span(4, 'Clause four carries a note.', 2, 1, comments=['Check the berth date.'])])
        self.assertEqual((sources[0]['media_type'], entries[0]['status']), (ingest.DOCX, 'ok'))
        # The record shape is accepted by the matter manifest validation.
        contracts.validate_matters({'schema_version': 1, 'data_class': 'public-synthetic', 'jurisdiction_profile': 'veld-fictional-v1',
                                    'source_set': 'candidate', 'matters': [{**basic(self).matters[0], 'sources': sources}]}, None)

    def test_macro_archive_and_traversal_members_are_refused(self):
        fake = Mock(return_value={'status': 'ok', 'units': []})
        with patch(INGEST + '.extractor', fake):
            cases = [(docx(['word/document.xml', 'word/vbaProject.bin']), 'raw/a.docx', 'unsupported', 'macro_content'),
                     (docx(['word/document.xml', '../x']), 'raw/b.docx', 'corrupt', 'archive_traversal'),
                     (docx(['/etc/word.xml']), 'raw/c.docx', 'corrupt', 'archive_traversal'),
                     (docx(['word/document.xml']), 'raw/d.docm', 'unsupported', 'macro_content'),
                     (b'not a zip archive', 'raw/e.docx', 'corrupt', 'bad_archive')]
            for data, name, status, reason in cases:
                with self.subTest(name=name):
                    sources, entries = self.one(data, name)
                    self.assertEqual((sources, entries[0]['status'], entries[0]['reason_codes']), ([], status, [reason]))
            msg = message('Bundle', 'The archive of the berth photos is attached.\n')
            msg.add_attachment(docx(['photo-1.txt']), maintype='application', subtype='zip', filename='photos.zip')
            sources, entries = ingest.ingest_bytes(msg.as_bytes(), name='raw/m.eml', namespace='evidence', kind='message', matter_id='t1-dock-a')
        fake.assert_not_called()
        self.assertEqual(len(sources), 1)
        self.assertEqual((entries[1]['status'], entries[1]['reason_codes'], entries[1]['media_type']), ('unsupported', ['archive_not_expanded'],
                                                                                                         'application/octet-stream'))


class VisibilityTests(unittest.TestCase):
    def test_wrong_role_and_missing_visibility_rule_are_rejected(self):
        brief = 'An earlier memo on the north dock recorded a charge.\n'

        def email_authority(p):
            p.add('raw/law.eml', message().as_bytes(), namespace='authority', authority=AUTHORITY)

        def evidence_without_matter(p):
            p.add('raw/loose.txt', 'A loose report.\n', namespace='evidence', kind='report')

        def file_without_rule(p):
            p.evidence('raw/c.txt', 'Another report.\n')
            p.rules.pop()

        def duplicate_rule(p):
            p.rules.append(dict(p.rules[0]))

        def uncollected_rule(p):
            p.rules.append({'path': 'raw/ghost.txt', 'source_set': 'candidate'})

        def grader_rule(p):
            p.evidence('raw/answer.txt', 'The answer is a charge.\n', source_set='grader')

        def review_authority(p):
            p.add('raw/law.txt', 'A master who berths at a closed dock commits an offence.\n', source_set='review', namespace='authority',
                  authority=AUTHORITY)

        def brief_excludes_only_its_own_matter(p):
            p.add('raw/brief.txt', brief, excluded=['t1-dock-a'], namespace='prior_brief', matter_id='t1-dock-a', kind='brief')

        def template_with_matter(p):
            p.add('raw/form.txt', 'A form.\n', namespace='template', matter_id='t1-dock-a', kind='template')

        cases = [(email_authority, 'Wrong role assignment: raw/law.eml'), (evidence_without_matter, 'Wrong role assignment: raw/loose.txt'),
                 (file_without_rule, 'Missing visibility rule: raw/c.txt'), (duplicate_rule, 'Duplicate visibility rule: raw/a/report.txt'),
                 (uncollected_rule, 'not collected: raw/ghost.txt'), (grader_rule, 'Wrong role assignment: raw/answer.txt'),
                 (review_authority, 'Wrong role assignment: raw/law.txt'), (brief_excludes_only_its_own_matter, 'Wrong role assignment: raw/brief.txt'),
                 (template_with_matter, 'Wrong role assignment: raw/form.txt')]
        for change, error in cases:
            with self.subTest(error=error):
                packet = basic(self)
                change(packet)
                with self.assertRaisesRegex(ValueError, error):
                    packet.ingest()
                self.assertFalse((packet.dir / 'matters.json').exists())
        packet = basic(self).add('raw/brief.txt', brief, excluded=['t1-dock-a', 't1-dock-b'], namespace='prior_brief', matter_id='t1-dock-a',
                                 kind='brief')
        packet.ingest()      # excluding every matter of its family is accepted
        # A duplicate may not carry a source into another set.
        packet = basic(self).evidence('raw/a/copy.txt', 'Dock report.\n\nThe ferry berthed at the north dock after it closed.\n', source_set='review')
        with self.assertRaisesRegex(ValueError, 'Wrong role assignment: raw/a/copy.txt'):
            packet.ingest()

    def test_candidate_manifests_hold_candidate_sources_only(self):
        review_text, oracle_text = 'Reviewer aside: the expected call is a decline.', 'Approved passage: the ferry berthed after closing.'
        packet = basic(self).evidence('raw/a/review.txt', review_text + '\n', source_set='review', kind='note')
        packet.evidence('raw/a/oracle.txt', oracle_text + '\n', source_set='oracle', kind='passage')
        suite = contracts.load_suite(packet.lock())
        candidate = (packet.dir / 'matters.json').read_text(encoding='utf-8') + (packet.dir / 'corpus.json').read_text(encoding='utf-8')
        self.assertNotIn(review_text, candidate)
        self.assertNotIn(oracle_text, candidate)
        self.assertEqual([(s['source_set'], s['matter_id'], s['spans'][0]['text']) for s in suite['review']['sources']], [('review', 't1-dock-a', review_text)])
        self.assertEqual([(s['source_set'], s['spans'][0]['text']) for s in suite['oracle']['sources']], [('oracle', oracle_text)])
        self.assertEqual((suite['review']['source_set'], suite['oracle']['source_set']), ('review', 'oracle'))
        pinned = contracts.pinned_files(packet.dir / 'suite.lock.json')
        self.assertIn(packet.dir.resolve() / 'oracle.json', pinned)
        self.assertIn(packet.dir.resolve() / 'review.json', pinned)
        view = contracts.candidate_view(suite)
        text = json.dumps(view)
        self.assertNotIn('Reviewer aside', text)
        self.assertNotIn('Approved passage', text)
        self.assertEqual([f['purpose'] for f in view['lock']['source_files']], ['matters', 'corpus'])
        for purpose in ('rubric', 'oracle', 'review', 'collection', 'visibility'):
            entry = next(f for f in suite['lock']['source_files'] if f['purpose'] == purpose)
            self.assertNotIn(entry['sha256'], text)
        moved = suite['review']['sources'][0]
        edit(packet.dir / 'matters.json', lambda m: m['matters'][0]['sources'].append({k: v for k, v in moved.items() if k != 'matter_id'}))
        edit(packet.dir / 'review.json', lambda r: r['sources'].clear())
        with self.assertRaisesRegex(ValueError, 'The matter manifest holds candidate sources only: ' + moved['source_id']):
            contracts.load_suite(relock(packet.dir))

    def test_sources_carry_their_source_set_and_exclusions(self):
        msg = message('Berth office', 'The berth office says the ferry berthed late.\n', headers={'Message-ID': '<b1@veld.example>'})
        msg.add_attachment(b'Berth office log for the night.\n', maintype='text', subtype='plain', filename='log.txt')
        packet = basic(self).evidence('raw/a/office.eml', msg.as_bytes(), kind='message')
        packet.add('raw/brief.txt', 'An earlier memo on the north dock recorded a charge.\n', excluded=['t1-dock-a', 't1-dock-b'],
                   namespace='prior_brief', matter_id='t1-dock-b', kind='brief')
        packet.add('raw/form.txt', 'Memo form: question, authority, elements, open points.\n', namespace='template', kind='template')
        packet.add('raw/law.txt', 'A master who berths a ferry at a closed dock commits an offence.\n', namespace='authority', authority=AUTHORITY)
        packet.evidence('raw/b/note.txt', 'A reviewer note on the second matter.\n', matter='t1-dock-b', source_set='review', kind='note')
        suite = contracts.load_suite(packet.lock())
        matters = {m['matter_id']: m for m in suite['matters']['matters']}
        everything = [s for m in matters.values() for s in m['sources']] + suite['matters']['shared_sources'] + suite['review']['sources']
        self.assertTrue(all('source_set' in s and 'excluded_matters' in s for s in everything))
        email_root, attachment = matters['t1-dock-a']['sources'][1:]
        self.assertEqual((attachment['parent_source_id'], attachment['source_set'], attachment['excluded_matters']),
                         (email_root['source_id'], 'candidate', []))
        self.assertEqual({s['role']: (s['source_set'], s['excluded_matters']) for s in suite['matters']['shared_sources']},
                         {'prior_brief': ('candidate', ['t1-dock-a', 't1-dock-b']), 'template': ('candidate', [])})
        self.assertEqual({s['role'] for m in matters.values() for s in m['sources']}, {'evidence'})
        [law] = suite['corpus']['authorities']
        raw = (packet.dir / 'raw/law.txt').read_bytes()
        self.assertEqual((law['text'], law['original_sha256']), ('A master who berths a ferry at a closed dock commits an offence.',
                                                                 hashlib.sha256(raw).hexdigest()))
        self.assertEqual({k: v for k, v in law.items() if k not in ('text', 'text_sha256', 'original_sha256')}, AUTHORITY)
        self.assertEqual([(s['role'], s['source_set'], s['matter_id']) for s in suite['review']['sources']], [('evidence', 'review', 't1-dock-b')])
        self.assertEqual(ingest.verify_anchors(suite), [])

    def test_escape_neutralises_markup(self):
        self.assertEqual(ingest.escape('<script>alert(1)</script>'), '&lt;script&gt;alert\\(1\\)&lt;/script&gt;')
        self.assertEqual(ingest.escape('[click](http://x.invalid)'), '\\[click\\]\\(http:\\/\\/x.invalid\\)')
        self.assertEqual(ingest.escape('run `rm` *now*\nnext line'), 'run \\`rm\\` \\*now\\* next line')
        self.assertEqual(ingest.escape('a "quote" & #1 | ~x_ !{}+-'), 'a &quot;quote&quot; &amp; \\#1 \\| \\~x\\_ \\!\\{\\}\\+\\-')
        self.assertNotIn('\n', ingest.escape('one\r\ntwo\rthree\n'))
        # Markdown punctuation is backslashed first and HTML-escaped after, so entities stay valid.
        self.assertEqual(ingest.escape("the respondent's boat"), 'the respondent&#x27;s boat')
        self.assertEqual(ingest.escape('see https://tracker.invalid/x'), 'see https:\\/\\/tracker.invalid/x')
        self.assertEqual(ingest.escape('www.tracker.invalid'), 'www\\.tracker.invalid')
        self.assertEqual(ingest.escape('1. recommend a charge'), '1\\. recommend a charge')
        self.assertEqual(ingest.escape('2024. A year, not a list'), '2024\\. A year, not a list')
        self.assertEqual(ingest.escape('pay \u202eredro\u202c now\u2066 x\u2069\u2028y\u2029'), 'pay \ufffdredro\ufffd now\ufffd x\ufffd\ufffdy\ufffd')

        def render(text):      # one Markdown inline pass: backslash escapes and entity references
            return re.sub(r'\\([!-/:-@\[-`{-~])|&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);',
                          lambda m: m.group(1) or html.unescape(m.group(0)), text)
        # GFM email and mailto autolinks, an indented code block, and more invisible or line-breaking characters.
        self.assertEqual(ingest.escape('write to a@b.example'), 'write to a\\@b.example')
        self.assertEqual(ingest.escape('mailto:a@b.example'), 'mailto:a\\@b.example')
        self.assertEqual(ingest.escape('    indented code'), '&#32;&#32;&#32;&#32;indented code')
        self.assertEqual(ingest.escape('\tx'), '&#9;x')
        self.assertEqual(ingest.escape('a\u200eb\u200fc\u061cd\ufeffe\u0085f\x0bg\x0ch'),
                         'a\ufffdb\ufffdc\ufffdd\ufffde\ufffdf\ufffdg\ufffdh')
        hidden = '\u200b\u200c\u200d\u2060\u00ad\u180e\u034f\u115f\u3164\U000e0000\U000e0041\U000e007f'
        self.assertEqual(ingest.escape('x'.join(hidden)), 'x'.join('\ufffd' * len(hidden)))
        self.assertEqual(ingest.escape('zero\u200bwidth'), 'zero\ufffdwidth')
        samples = ["the respondent's boat", '<b>bold</b> & &amp; \\ `code` [x](y) # h', 'https://e.invalid and <http://e.invalid>',
                   '1. item', 'a | b ~ c * d _ e', '"quoted" & #1', 'mail a@b.example or mailto:a@b.example', '    four spaces first',
                   '1.5 kg delivered to Mr. Smith on 2025-05-02']
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(render(ingest.escape(sample)), sample)      # exactly one rendering pass restores the text
        self.assertNotEqual(render(ingest.escape(ingest.escape('"quoted" & #1'))), '"quoted" & #1')      # callers must not escape twice
        self.assertIn('not escape twice', ingest.escape.__doc__)


class LockTests(unittest.TestCase):
    def packet(self):
        packet = basic(self).evidence('raw/a/review.txt', 'A reviewer note.\n', source_set='review', kind='note')
        packet.lock()
        return packet

    def test_extended_lock_pins_every_original_and_manifest(self):
        packet = self.packet()
        lock = packet.dir / 'suite.lock.json'
        names = [p.relative_to(packet.dir.resolve()).as_posix() for p in contracts.pinned_files(lock)]
        self.assertEqual(names, ['matters.json', 'corpus.json', 'rubric.json', 'collection.json', 'visibility.json', 'review.json',
                                 'raw/a/report.txt', 'raw/a/review.txt', 'raw/b/report.txt'])
        self.assertEqual([e['purpose'] for e in read_json(lock)['source_files']][-3:], ['source'] * 3)
        suite = contracts.load_suite(lock)
        self.assertEqual(set(suite['originals']), {sha256_file(packet.dir / p) for p in ('raw/a/report.txt', 'raw/a/review.txt', 'raw/b/report.txt')})
        self.assertEqual(suite['dataset'], None)
        self.assertEqual(suite['collection'], packet.json('collection.json'))
        self.assertEqual(contracts.lock_files(lock)[1]['review'], packet.dir.resolve() / 'review.json')
        cases = [(('visibility',), 'Suite needs both a collection and a visibility manifest'),
                 (('collection', 'visibility'), 'An oracle or review manifest needs a collection manifest'),
                 (('collection', 'visibility', 'review'), 'Source files need a collection or a dataset lock')]
        saved = lock.read_bytes()
        for drop, message_text in cases:
            with self.subTest(drop=drop):
                with self.assertRaisesRegex(ValueError, message_text):
                    contracts.load_suite(relock(packet.dir, drop))
                lock.write_bytes(saved)
        with patch.object(contracts, 'MAX_SOURCE_FILES', 2), self.assertRaisesRegex(ValueError, 'more than 2 source files'):
            contracts.load_suite(lock)
        with patch.object(contracts, 'MAX_SUITE_BYTES', 1000), self.assertRaisesRegex(ValueError, 'exceed 1000 bytes'):
            contracts.load_suite(lock)
        with self.assertRaisesRegex(ValueError, 'Duplicate suite file purpose: review'):
            edit(lock, lambda l: l['source_files'].append(dict(l['source_files'][5])))
            contracts.load_suite(lock)
        lock.write_bytes(saved)
        # Every JSON file is read once, from the bytes whose digest is compared with its lock entry.
        real, reads = contracts.read_json_strict, []

        def counting(path):
            reads.append(Path(path).name)
            return real(path)
        with patch.object(contracts, 'read_json_strict', counting):
            contracts.load_suite(lock)
        self.assertEqual(sorted(reads), sorted(['suite.lock.json', 'matters.json', 'corpus.json', 'rubric.json', 'collection.json',
                                                'visibility.json', 'review.json']))

        for name in ('collection.json', 'visibility.json', 'review.json'):
            with self.subTest(swapped=name):
                original = (packet.dir / name).read_bytes()

                def swapping(path, name=name, original=original):
                    if Path(path).name == name:      # replaced after the lock hashed it and before it is parsed
                        Path(path).write_bytes(original.replace(b'{', b'{ ', 1))
                    return real(path)
                with patch.object(contracts, 'read_json_strict', swapping), self.assertRaisesRegex(ValueError, 'stale: ' + name):
                    contracts.load_suite(lock)
                (packet.dir / name).write_bytes(original)

    def test_post_lock_mutation_and_unresolved_anchor_are_rejected(self):
        packet = basic(self).add('raw/brief.txt', 'An earlier memo on the north dock recorded a charge.\n', excluded=['t1-dock-a', 't1-dock-b'],
                                 namespace='prior_brief', matter_id='t1-dock-a', kind='brief')
        packet.evidence('raw/a/review.txt', 'A reviewer note.\n', source_set='review', kind='note')
        lock = packet.lock()
        saved = {p: p.read_bytes() for p in packet.dir.rglob('*') if p.is_file()}

        def restore():
            for path, data in saved.items():
                path.write_bytes(data)
        raw = packet.dir / 'raw/a/report.txt'
        raw.write_bytes(raw.read_bytes().replace(b'north', b'North', 1))      # one byte of a raw file
        with self.assertRaisesRegex(ValueError, 'stale: raw/a/report.txt'):
            contracts.load_suite(lock)
        restore()
        source = packet.json('matters.json')['matters'][0]['sources'][0]
        edit(packet.dir / 'matters.json', lambda m: m['matters'][0]['sources'][0]['spans'][0].pop('locator'))
        with self.assertRaisesRegex(ValueError, 'Unresolved anchor: ' + source['source_id']):
            contracts.load_suite(relock(packet.dir))
        restore()
        with self.assertRaisesRegex(ValueError, 'Unresolved anchor: original file is not pinned'):
            contracts.load_suite(relock(packet.dir, drop=('raw/a/report.txt',)))
        restore()
        edit(packet.dir / 'review.json', lambda r: r['sources'][0].update(source_set='oracle'))
        with self.assertRaisesRegex(ValueError, 'Source visibility differs from the visibility manifest'):
            contracts.load_suite(relock(packet.dir))
        restore()
        edit(packet.dir / 'matters.json', lambda m: m['shared_sources'][0].update(excluded_matters=['t1-dock-b']))
        with self.assertRaisesRegex(ValueError, 'Source visibility differs from the visibility manifest: ' + packet.json('matters.json')['shared_sources'][0]['source_id']):
            contracts.load_suite(relock(packet.dir))
        restore()
        edit(packet.dir / 'collection.json', lambda c: c.update(jurisdiction_profile='veld-other-v1'))
        with self.assertRaisesRegex(ValueError, 'Conflicting jurisdiction profile between the lock and the collection manifest'):
            contracts.load_suite(relock(packet.dir))
        restore()
        edit(packet.dir / 'review.json', lambda r: r['sources'][0].update(matter_id='t9-ghost-a'))
        with self.assertRaisesRegex(ValueError, 'A source of the review manifest must name a matter of the suite or null'):
            contracts.load_suite(relock(packet.dir))
        restore()
        edit(packet.dir / 'review.json', lambda r: r['sources'].append(copy.deepcopy(packet.json('matters.json')['matters'][0]['sources'][0])))
        with self.assertRaisesRegex(ValueError, 'Duplicate source'):
            contracts.load_suite(relock(packet.dir))      # a source id is unique across all manifests
        restore()

        def retext(m):      # consistent with its own digest, but not with the pinned original
            span = m['matters'][0]['sources'][0]['spans'][1]
            span.update(text='The ferry never berthed.', text_sha256=contracts.text_digest('The ferry never berthed.'))
        edit(packet.dir / 'matters.json', retext)
        with self.assertRaisesRegex(ValueError, 'Suite anchors do not verify: matters.json: differs from the manifest generated'):
            contracts.load_suite(relock(packet.dir))
        with patch.object(ingest, '_generated_problems', return_value=[]):      # past the load, the span check still names the span
            suite = contracts.load_suite(packet.dir / 'suite.lock.json')
        self.assertEqual(ingest.verify_anchors(suite), ['matters.json: differs from the manifest generated from the collection',
                                                        source['source_id'] + '#2: span text differs from the original at its locator'])
        restore()
        self.assertEqual(ingest.verify_anchors(contracts.load_suite(lock)), [])

    def test_inline_sources_are_refused_in_public_benchmark_suites(self):
        out = AdapterTests.imported(self)
        AdapterTests.verify_all(out)
        contracts.load_suite(out / 'suite.lock.json')
        inline = {'source_id': 'inline-note', 'role': 'evidence', 'version': '1', 'kind': 'note',
                  'spans': [{'span_id': 'inline-note#1', 'text': 'An inline note.', 'text_sha256': contracts.text_digest('An inline note.')}]}
        edit(out / 'matters.json', lambda m: m['shared_sources'].append(inline))
        edit(out / 'dataset.lock.json', lambda d: next(x for x in d['derived'] if x['path'] == 'matters.json').update(
            sha256=sha256_file(out / 'matters.json')))
        with self.assertRaisesRegex(ValueError, 'Unresolved anchor: inline source in a release suite: inline-note'):
            contracts.load_suite(relock(out))
        self.assertEqual(contracts.load_suite(SMOKE / 'suite.lock.json')['lock']['data_class'], 'public-synthetic')
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / 'suite'
            shutil.copytree(SMOKE, copy_dir)
            for name in ('matters.json', 'corpus.json', 'rubric.json'):
                edit(copy_dir / name, lambda v: v.update(data_class='private-matter'))
            suite = contracts.load_suite(relock(copy_dir, data_class='private-matter'))
            self.assertEqual(suite['lock']['data_class'], 'private-matter')
            with self.assertRaisesRegex(ValueError, 'public-synthetic suites only'):
                legal.validate({'suite': str(copy_dir / 'suite.lock.json'), 'synthetic': True}, ROOT)

    def test_generated_manifest_above_the_file_limit_is_refused(self):
        packet = basic(self)
        with patch.object(contracts, 'MAX_SOURCE_BYTES', 600), \
                self.assertRaisesRegex(ValueError, 'Generated manifest exceeds the per-file limit: matters.json'):
            packet.ingest()
        self.assertEqual(sorted(p.name for p in packet.dir.iterdir()), ['collection.json', 'raw', 'visibility.json'])

    def test_private_matter_ingestion_is_refused(self):
        packet = Packet(self, data_class='private-matter').evidence('raw/a.txt', 'A report.\n')
        with self.assertRaisesRegex(ValueError, 'Private matter ingestion is not available'):
            packet.ingest()
        self.assertEqual(sorted(p.name for p in packet.dir.iterdir()), ['collection.json', 'raw', 'visibility.json'])

    def test_negative_sizes_cannot_lower_the_suite_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / 'packets'
            shutil.copytree(PACKETS, copy_dir)
            edit(copy_dir / 'suite.lock.json', lambda l: l['source_files'][-1].update(size=-10 ** 9))
            with self.assertRaisesRegex(ValueError, 'Suite file size is invalid or above the limit: raw/'):
                contracts.load_suite(copy_dir / 'suite.lock.json')

    def test_generated_manifests_must_match_the_collection(self):
        def matter(v, matter_id):
            return next(x for x in v['matters'] if x['matter_id'] == matter_id)

        def move(v):
            a, b = matter(v, 'p2-kiln-a'), matter(v, 'p2-kiln-b')
            statement = next(s for s in a['sources'] if s['kind'] == 'statement')
            a['sources'].remove(statement)
            b['sources'].append(statement)

        def email(v):
            source = next(s for s in matter(v, 'p1-quay-b')['sources'] if 'email' in s)
            source['email'].update(date='2024-08-13T07:15:00+00:00', sender_role='respondent')

        def forge(v):
            for a in v['authorities']:
                if (a['authority_id'], a['version']) == ('vho-9-2', '2025'):
                    a.update(snapshot={'id': 'forged', 'published': '2025-12-02'}, citation='Forged citation')
        cases = {
            'source moved to another matter': ('matters.json', move),
            'source dropped': ('matters.json', lambda v: matter(v, 'p2-kiln-a')['sources'].pop()),
            'email date and sender role': ('matters.json', email),
            'operative date and question': ('matters.json', lambda v: matter(v, 'p1-quay-a').update(operative_date='2025-06-02',
                                                                                                  question='Recommend a charge. Why?')),
            'family id': ('matters.json', lambda v: matter(v, 'p1-quay-b').update(family_id='p9-other')),
            'role and kind': ('matters.json', lambda v: matter(v, 'p2-kiln-a')['sources'][1].update(kind='brief')),
            'authority citation and snapshot': ('corpus.json', forge),
            'cutoff and policy': ('corpus.json', lambda v: v.update(availability_cutoff='2025-12-31', policy={**v['policy'], 'policy_id': 'other'})),
            'operative date in the collection only': ('collection.json', lambda v: matter(v, 'p1-quay-a').update(operative_date='2025-05-01')),
            'visibility only': ('visibility.json', lambda v: next(r for r in v['rules'] if r['path'].endswith('prior-brief.txt')).update(
                excluded_matters=['p1-quay-a', 'p1-quay-b', 'p2-kiln-a'])),
        }
        names = {'collection.json': 'matters.json', 'visibility.json': 'matters.json'}
        for label, (name, change) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                copy_dir = Path(tmp) / 'packets'
                shutil.copytree(PACKETS, copy_dir)
                edit(copy_dir / name, change)
                generated = names.get(name, name)
                if label == 'visibility only':      # the stamped exclusions already contradict the edited rule at load
                    with self.assertRaisesRegex(ValueError, 'Source visibility differs from the visibility manifest'):
                        ingest.lock_suite(copy_dir, benchmark_id='legal-original-packets', revision='2026-11-11.1', split_id='calibration')
                    continue
                with self.assertRaisesRegex(ValueError, 'Suite anchors do not verify: .*' + re.escape(generated)):
                    ingest.lock_suite(copy_dir, benchmark_id='legal-original-packets', revision='2026-11-11.1', split_id='calibration')
                self.assertEqual((copy_dir / 'suite.lock.json').read_bytes(), (PACKETS / 'suite.lock.json').read_bytes())
                with self.assertRaisesRegex(ValueError, 'Suite anchors do not verify: .*' + re.escape(generated)):
                    contracts.load_suite(relock(copy_dir))      # a hand relock does not get past the load either

    def test_a_hand_relocked_tampered_manifest_does_not_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / 'packets'
            shutil.copytree(PACKETS, copy_dir)
            edit(copy_dir / 'matters.json', lambda v: next(x for x in v['matters'] if x['matter_id'] == 'p1-quay-a').update(operative_date='2025-06-02'))
            lock = relock(copy_dir)      # make_lock only, without lock_suite
            with self.assertRaisesRegex(ValueError, 'Suite anchors do not verify: matters.json: differs from the manifest generated'):
                contracts.load_suite(lock)
            with self.assertRaisesRegex(ValueError, 'Suite anchors do not verify: matters.json'):
                legal.validate({'suite': str(lock), 'synthetic': True}, ROOT)
        # The regeneration runs in memory for a collection suite only: nothing is written, nothing is fetched.
        real, calls = ingest._manifests, []

        def counting(*args, **kwargs):
            calls.append(args[0])
            return real(*args, **kwargs)
        before = {p: p.stat().st_mtime_ns for p in PACKETS.rglob('*')}
        with patch.object(ingest, '_manifests', counting), patch('socket.socket', side_effect=AssertionError('network access')):
            contracts.load_suite(SMOKE / 'suite.lock.json')
            self.assertEqual(calls, [])      # a suite without a collection never calls the ingester
            suite = contracts.load_suite(PACKETS / 'suite.lock.json')
            self.assertEqual(len(calls), 1)
        self.assertEqual({p: p.stat().st_mtime_ns for p in PACKETS.rglob('*')}, before)
        self.assertEqual(suite['lock']['benchmark_id'], 'legal-original-packets')

    def test_one_path_validator_rejects_streams_and_unnormalised_paths(self):
        self.assertIs(ingest._relative, contracts._relative)
        self.assertIs(benchmarks._relative, contracts._relative)
        bad = ['raw/a/carrier:hidden.txt', 'raw/a.txt:hidden', './x', 'a//b', 'a/./b', 'raw/a/', 'raw/' + 'x' * 300 + '.txt']
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for path in bad:
            with self.subTest(entry='contracts._inside', path=path), self.assertRaisesRegex(ValueError, 'Suite path'):
                contracts._inside(root, path)
            with self.subTest(entry='collection', path=path):
                packet = basic(self).evidence(path if ':' not in path and len(path) < 255 and not path.endswith('/') else 'raw/a/ok.txt', 'Text.\n')
                packet.files[-1]['path'] = packet.rules[-1]['path'] = path
                with self.assertRaisesRegex(ValueError, 'Suite path'):
                    packet.ingest()
            with self.subTest(entry='dataset lock', path=path):
                dataset = benchmarks.verify_dataset(AdapterTests.imported(self) / 'dataset.lock.json') if path == bad[0] else dataset
                value = copy.deepcopy(dataset)
                value['files'][0]['path'] = path
                with self.assertRaisesRegex(ValueError, 'relative POSIX path|Suite path'):
                    benchmarks.validate_dataset(value)
        with tempfile.TemporaryDirectory() as tmp:      # a suite lock entry naming an alternate data stream
            copy_dir = Path(tmp) / 'packets'
            shutil.copytree(PACKETS, copy_dir)
            edit(copy_dir / 'suite.lock.json', lambda l: l['source_files'][-1].update(path=l['source_files'][-1]['path'] + ':hidden'))
            with self.assertRaisesRegex(ValueError, 'Suite path'):
                contracts.load_suite(copy_dir / 'suite.lock.json')
        packet = basic(self).evidence('raw/A/REPORT.TXT', 'Dock report.\n', matter='t1-dock-b')      # a case variant is the same file on Windows
        with self.assertRaisesRegex(ValueError, 'Duplicate collected file: raw/A/REPORT.TXT'):
            packet.ingest()


# FORMAT FIXTURES: original fictional documents in the assumed layout of the upstream benchmark; not the dataset.
DOC_A = ('Lantern Kettle Company privacy notice, a fictional format fixture.\n\n'
         'We keep the order history of a customer for two years after the last order.\n\n'
         'We share delivery addresses only with the courier that carries the parcel.\n')
DOC_B = ('Orchard Lane Library card terms, a fictional format fixture.\r\n\r\n'
         'A borrower may ask the desk to delete the reading history at any time.\r\n')
KEPT = 'We keep the order history of a customer for two years'
DELETE = 'A borrower may ask the desk to delete the reading history'


def tests():
    a, b = DOC_A.index(KEPT), DOC_B.index(DELETE)
    return [{'query': 'How long is the order history of a customer kept?',
             'snippets': [{'file_path': 'privacy_qa/lantern.txt', 'span': [a, a + len(KEPT)], 'answer': KEPT}]},
            {'query': 'Can a borrower have the reading history deleted?',
             'snippets': [{'file_path': 'privacy_qa/orchard.txt', 'span': [b, b + len(DELETE)], 'answer': DELETE}]},
            {'query': 'Who reads the harbor notice?', 'snippets': [{'file_path': 'privacy_qa/absent.txt', 'span': [0, 10], 'answer': 'x'}]},
            {'query': 'What is shared with the courier?', 'snippets': [{'file_path': 'privacy_qa/lantern.txt', 'span': [5, 10000], 'answer': 'y'}]}]


class AdapterTests(unittest.TestCase):
    @staticmethod
    def upstream(test, adapter='legalbench-rag', expected=None, upstream_tests=None, limit=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        files = {'upstream/corpus/privacy_qa/lantern.txt': DOC_A.encode(), 'upstream/corpus/privacy_qa/orchard.txt': DOC_B.encode(),
                 'upstream/benchmarks/privacy_qa.json': ingest._dump({'tests': tests() if upstream_tests is None else upstream_tests})}
        for relative, data in files.items():
            (base / relative).parent.mkdir(parents=True, exist_ok=True)
            (base / relative).write_bytes(data)
        digests = expected if expected is not None else [{'path': r[len('upstream/'):], 'sha256': hashlib.sha256(d).hexdigest()}
                                                          for r, d in sorted(files.items())]
        dump(base / 'request.json', {
            'schema_version': 1, 'adapter': adapter, 'source_dir': 'upstream', 'component': 'privacy_qa', 'split': 'mini', 'limit': limit,
            'expected_files': digests,
            'upstream': {'name': 'LegalBench-RAG format fixture', 'revision': 'fixture-1', 'source_date': '2026-01-15', 'publication_status': 'preprint',
                         'origin': 'format-fixture/original-text', 'annotation_origin': 'format-fixture/test-author'},
            'license': {'name': 'format-fixture-only', 'scope': ['questions', 'documents']}, 'jurisdiction': 'us-contract-privacy'})
        return base

    @staticmethod
    def imported(test, nonce=NONCE, name='import'):
        base = AdapterTests.upstream(test)
        benchmarks.import_dataset(base / 'request.json', base / name, nonce=nonce)
        return base / name

    @staticmethod
    def native(out, examples, scorer='legalbench-rag-scorer@fixture-1'):
        dump(out.parent / 'native.json', {'scorer': scorer, 'examples': examples})
        return out.parent / 'native.json'

    @staticmethod
    def gold_ranges(out):
        return {g['upstream_id']: benchmarks._ranges(g['upstream_labels']) for g in read_json(out / 'rubric.json')['matters']}

    @staticmethod
    def verify_all(out):
        lock = out / 'dataset.lock.json'
        for gate in ('license', 'jurisdiction', 'split'):
            benchmarks.set_gate(lock, gate, evidence='operator-check-1', verified_by='operator-a', verified_utc='2026-11-12T00:00:00Z')
        examples = [{'upstream_id': uid, 'retrieved': gold, 'precision': 1.0, 'recall': 1.0} for uid, gold in AdapterTests.gold_ranges(out).items()]
        benchmarks.parity_check(lock, AdapterTests.native(out, examples))
        benchmarks.set_gate(lock, 'grader_parity', evidence='parity-run-1', verified_by='operator-a', verified_utc='2026-11-12T00:00:00Z')
        relock(out)

    def test_format_fixture_import_preserves_upstream_ids_and_records_rejections(self):
        out = self.imported(self)
        dataset = benchmarks.verify_dataset(out / 'dataset.lock.json')
        self.assertEqual(dataset['examples'], {'total': 4, 'upstream_total': 4, 'imported': 2,
                                               'rejected': [{'upstream_id': 'privacy_qa:3', 'reason_code': 'span_out_of_range'}],
                                               'missing': [{'upstream_id': 'privacy_qa:2', 'file_path': 'privacy_qa/absent.txt'}]})
        self.assertEqual((dataset['upstream']['origin'], dataset['upstream']['annotation_origin']),
                         ('format-fixture/original-text', 'format-fixture/test-author'))
        self.assertEqual(dataset['protocol'], {'reduced': True, 'adaptations': ['no-operative-date', 'no-venue', 'paragraph-chunking-1000']})
        self.assertEqual((dataset['dataset_id'], dataset['adapter'], dataset['split'], dataset['jurisdiction']),
                         ('legalbench-rag-privacy-qa-mini', 'legalbench-rag', 'mini', 'us-contract-privacy'))
        self.assertEqual([f['path'] for f in dataset['files']], ['benchmarks/privacy_qa.json', 'corpus/privacy_qa/lantern.txt',
                                                                 'corpus/privacy_qa/orchard.txt'])
        self.assertEqual([d['path'] for d in dataset['derived']], ['corpus.json', 'matters.json', 'rubric.json'])
        self.assertEqual({g: v['status'] for g, v in dataset['gates'].items()},
                         {'bytes': 'verified', 'license': 'blocked', 'jurisdiction': 'blocked', 'split': 'blocked', 'grader_parity': 'blocked'})
        rubric, matters = read_json(out / 'rubric.json'), read_json(out / 'matters.json')
        entries = {g['upstream_id']: g for g in rubric['matters']}
        self.assertEqual(set(entries), {'privacy_qa:0', 'privacy_qa:1'})
        a, b = DOC_A.index(KEPT), DOC_B.index(DELETE)
        self.assertEqual(entries['privacy_qa:0']['upstream_labels'], {'answers': [KEPT], 'ranges': [f'privacy_qa/lantern.txt:{a}-{a + len(KEPT)}']})
        self.assertEqual(entries['privacy_qa:1']['upstream_labels'], {'answers': [DELETE], 'ranges': [f'privacy_qa/orchard.txt:{b}-{b + len(DELETE)}']})
        spans = {s['span_id']: s['text'] for s in matters['shared_sources'] for s in s['spans']}
        self.assertEqual([spans[i] for i in entries['privacy_qa:0']['gold_spans']], [KEPT + ' after the last order.'])
        self.assertEqual([spans[i] for i in entries['privacy_qa:1']['gold_spans']], [DELETE + ' at any time.'])      # CRLF offsets mapped
        self.assertEqual({m['posture'] for m in matters['matters']}, {'retrieval'})
        self.assertEqual({(m['venue'], m['operative_date'], m['output_schema']) for m in matters['matters']},
                         {('unspecified', '2026-01-15', 'retrieval-result-v1')})
        candidate = (out / 'matters.json').read_text(encoding='utf-8') + (out / 'corpus.json').read_text(encoding='utf-8')
        for leak in ('privacy_qa:', 'upstream_labels', 'gold_spans', '"answers"'):
            self.assertNotIn(leak, candidate)
        self.assertEqual((rubric['data_class'], read_json(out / 'suite.lock.json')['data_class']), ('public-benchmark', 'public-benchmark'))
        # A wrong expected digest leaves the bytes gate blocked.
        base = self.upstream(self, expected=[{'path': 'benchmarks/privacy_qa.json', 'sha256': '0' * 64}])
        report = benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        self.assertEqual(report['blocked'], list(benchmarks.GATES))

    def test_imported_identifiers_are_not_derivable_from_gold(self):
        first, second = self.imported(self), self.imported(self, nonce='cd' * 16)
        families = [{m['question']: m['family_id'] for m in read_json(out / 'matters.json')['matters']} for out in (first, second)]
        self.assertEqual(set(families[0]), set(families[1]))
        self.assertTrue(all(families[0][q] != families[1][q] for q in families[0]))
        paths = ['privacy_qa/lantern.txt', 'privacy_qa/orchard.txt', 'corpus/privacy_qa/lantern.txt', 'corpus/privacy_qa/orchard.txt']
        unsalted = {'d-' + hashlib.sha256(p.encode()).hexdigest()[:12] for p in paths}
        self.assertFalse(set(families[0].values()) & unsalted)
        self.assertEqual(read_json(first / 'rubric.json')['import_nonce'], NONCE)
        for name in ('matters.json', 'corpus.json', 'dataset.lock.json', 'suite.lock.json'):
            self.assertNotIn(NONCE, (first / name).read_text(encoding='utf-8'))
        matter_ids = [m['matter_id'] for m in read_json(first / 'matters.json')['matters']]
        self.assertEqual(matter_ids, [m['matter_id'] for m in read_json(second / 'matters.json')['matters']])
        self.assertTrue(all(h[2:] not in ''.join(matter_ids) for h in unsalted))

    def test_parity_spot_check_matches_hand_computed_native_scores(self):
        scores = benchmarks.span_scores([{'file_path': 'a.txt', 'span': [0, 10]}, {'file_path': 'a.txt', 'span': [5, 15]},
                                         {'file_path': 'b.txt', 'span': [0, 5]}],
                                        [{'file_path': 'a.txt', 'span': [10, 20]}])
        self.assertEqual(scores, {'precision': 5 / 20, 'recall': 5 / 10})
        self.assertEqual(benchmarks.span_scores([], [{'file_path': 'a.txt', 'span': [0, 4]}]), {'precision': None, 'recall': 0.0})
        self.assertEqual(benchmarks.span_scores([{'file_path': 'a.txt', 'span': [0, 4]}], []), {'precision': 0.0, 'recall': None})
        out = self.imported(self)
        lock = out / 'dataset.lock.json'
        gold = self.gold_ranges(out)
        (path, (start, end)), = [(g['file_path'], g['span']) for g in gold['privacy_qa:0']]
        half = start + (end - start) // 2
        hand = {'precision': 1.0, 'recall': (half - start) / (end - start)}
        examples = [{'upstream_id': 'privacy_qa:0', 'retrieved': [{'file_path': path, 'span': [start, half]}], **hand},
                    {'upstream_id': 'privacy_qa:1', 'retrieved': [], 'precision': 0.0, 'recall': 0.0}]
        parity = benchmarks.parity_check(lock, self.native(out, examples))
        self.assertEqual((parity['status'], parity['max_abs_difference'], parity['scorer']), ('match', 0.0, 'legalbench-rag-scorer@fixture-1'))
        # Each metric is compared when its own local denominator is not empty: the empty retrieval has no precision, but its
        # recall (0.0) is compared.
        self.assertEqual([(s['upstream_id'], s['precision_denominator_empty'], s['recall_denominator_empty'], s['difference'])
                          for s in parity['sample']], [('privacy_qa:0', False, False, 0.0), ('privacy_qa:1', True, False, 0.0)])
        self.assertEqual(benchmarks.verify_dataset(lock)['parity'], parity)
        examples[0]['recall'] = hand['recall'] + 0.25
        parity = benchmarks.parity_check(lock, self.native(out, examples))
        self.assertEqual((parity['status'], parity['max_abs_difference']), ('mismatch', 0.25))
        disagree = [{**examples[0], 'recall': hand['recall']}, {**examples[1], 'recall': 1.0}]      # reviewer probe p4 case B
        parity = benchmarks.parity_check(lock, self.native(out, disagree))
        self.assertEqual((parity['status'], parity['max_abs_difference'], parity['sample'][1]['difference']), ('mismatch', 1.0, 1.0))
        unknown = [{**examples[0], 'recall': None}]      # a compared metric needs a native number: no row can record it
        with self.assertRaisesRegex(ValueError, 'Native example has no recall to compare: privacy_qa:0'):
            benchmarks.parity_check(lock, self.native(out, unknown))
        with self.assertRaisesRegex(ValueError, 'not in the import'):
            benchmarks.parity_check(lock, self.native(out, [{**examples[0], 'upstream_id': 'privacy_qa:2'}]))

    def test_unusual_upstream_paths_reject_only_their_example(self):
        a = DOC_A.index(KEPT)
        odd = ['privacy_qa/./lantern.txt', 'privacy_qa//lantern.txt', 'privacy_qa/' + 'y' * 300 + '.txt',
               'privacy_qa/lantern.txt:hidden', '../benchmarks/privacy_qa.json']
        upstream = tests() + [{'query': f'Odd path {i}?', 'snippets': [{'file_path': fp, 'span': [a, a + len(KEPT)], 'answer': KEPT}]}
                              for i, fp in enumerate(odd)]
        base = self.upstream(self, upstream_tests=upstream)
        report = benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        self.assertEqual(report['examples']['imported'], 2)
        self.assertEqual(report['examples']['rejected'][1:], [{'upstream_id': f'privacy_qa:{4 + i}', 'reason_code': 'unsafe_path'} for i in range(len(odd))])
        self.assertEqual(sorted(p.relative_to(base / 'import').as_posix() for p in (base / 'import' / 'originals').rglob('*') if p.is_file()),
                         ['originals/privacy_qa/lantern.txt', 'originals/privacy_qa/orchard.txt'])

    def test_an_upstream_path_must_spell_the_real_file_name(self):
        a = DOC_A.index(KEPT)
        upstream = [{'query': 'How long is the order history kept?',
                     'snippets': [{'file_path': 'privacy_qa/LANTERN.TXT', 'span': [a, a + len(KEPT)], 'answer': KEPT}]}] + tests()
        base = self.upstream(self, upstream_tests=upstream)
        report = benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        # The same report on every file system: a case variant of a real entry is refused, whether or not it would open.
        self.assertEqual(report['examples']['rejected'][0], {'upstream_id': 'privacy_qa:0', 'reason_code': 'unsafe_path'})
        # the correctly spelled path that follows is imported, not refused as a variant of the wrong spelling
        self.assertEqual(report['examples']['imported'], 2)
        copies = sorted(p.relative_to(base / 'import').as_posix() for p in (base / 'import/originals').rglob('*') if p.is_file())
        self.assertEqual(copies, ['originals/privacy_qa/lantern.txt', 'originals/privacy_qa/orchard.txt'])

    def test_a_failed_import_leaves_nothing_behind(self):
        base = self.upstream(self)
        before = sorted(p.name for p in base.iterdir())
        with patch.object(benchmarks.ingest, 'verify_anchors', return_value=['forced problem']), \
                self.assertRaisesRegex(ValueError, 'Imported suite anchors do not verify: forced problem'):
            benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        self.assertEqual(sorted(p.name for p in base.iterdir()), before)
        benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        with self.assertRaisesRegex(ValueError, 'The import output directory must be new or empty'):
            benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        # The output directory appears between the check and the move into place (reviewer probe p10).
        base = self.upstream(self)
        before = sorted(p.name for p in base.iterdir())
        real_rename = Path.rename

        def racing(path, target):
            Path(target).mkdir(exist_ok=True)
            (Path(target) / 'intruder.txt').write_text('x')
            return real_rename(path, target)
        with patch.object(Path, 'rename', racing), \
                self.assertRaisesRegex(ValueError, 'The import output directory appeared during the import'):
            benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        self.assertEqual(sorted(p.name for p in base.iterdir()), sorted(before + ['import']))
        self.assertEqual([p.name for p in (base / 'import').iterdir()], ['intruder.txt'])      # the intruder is left alone

    def test_limited_imports_record_the_upstream_total(self):
        base = self.upstream(self, limit=2)
        benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        dataset = benchmarks.verify_dataset(base / 'import/dataset.lock.json')
        self.assertEqual((dataset['examples']['total'], dataset['examples']['upstream_total'], dataset['examples']['imported']), (2, 4, 2))
        self.assertIn('limit-2', dataset['protocol']['adaptations'])
        self.assertTrue(dataset['protocol']['reduced'])
        broken = copy.deepcopy(dataset)
        broken['examples']['upstream_total'] = 1
        with self.assertRaisesRegex(ValueError, 'upstream_total'):
            benchmarks.validate_dataset(broken)

    def test_the_benchmark_digest_is_the_digest_of_the_bytes_parsed(self):
        base = self.upstream(self)
        real = contracts.read_json_strict

        def reading(path):
            value, digest = real(path)
            return (value, 'f' * 64) if Path(path).name == 'privacy_qa.json' else (value, digest)
        with patch.object(benchmarks.contracts, 'read_json_strict', reading):
            benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
        files = benchmarks.verify_dataset(base / 'import/dataset.lock.json')['files']
        self.assertEqual(next(f['sha256'] for f in files if f['path'] == 'benchmarks/privacy_qa.json'), 'f' * 64)

    def test_gated_adapters_and_repository_outputs_are_refused(self):
        for adapter in ('ecfr-temporal', 'legalreasonbench-sample', 'harvey-public'):
            with self.subTest(adapter=adapter):
                self.assertFalse(benchmarks.ADAPTERS[adapter]['available'])
                base = self.upstream(self, adapter=adapter)
                with self.assertRaisesRegex(ValueError, f'Adapter {adapter} is gated: release_format_unverified'):
                    benchmarks.import_dataset(base / 'request.json', base / 'import', nonce=NONCE)
                self.assertFalse((base / 'import').exists())
        base = self.upstream(self)
        target = ROOT / 'experiments' / 'legal-benchmark' / 'workloads' / 'imported-test-output'
        with self.assertRaisesRegex(ValueError, 'Dataset imports must stay outside the repository tree'):
            benchmarks.import_dataset(base / 'request.json', target, nonce=NONCE)
        self.assertFalse(target.exists())
        self.assertEqual(benchmarks.ADAPTERS['legalbench-rag']['cohort'], 'contract-privacy')

    def test_tracked_workloads_are_public_synthetic_only(self):
        locks = sorted((X / 'workloads').glob('*/suite.lock.json'))
        self.assertEqual([p.parent.name for p in locks], ['original-packets', 'original-smoke'])
        self.assertEqual({read_json(p)['data_class'] for p in locks}, {'public-synthetic'})
        self.assertFalse(list((X / 'workloads').glob('**/dataset.lock.json')))


class DatasetLockTests(unittest.TestCase):
    def test_public_benchmark_suite_is_blocked_until_every_gate_is_verified(self):
        out = AdapterTests.imported(self)
        lock, dataset_lock = out / 'suite.lock.json', out / 'dataset.lock.json'
        with self.assertRaisesRegex(ValueError, 'Dataset import gate is blocked: license, jurisdiction, split, grader_parity$'):
            contracts.load_suite(lock)
        stamp = {'evidence': 'operator-check-1', 'verified_by': 'operator-a', 'verified_utc': '2026-11-12T00:00:00Z'}
        for gate in ('license', 'jurisdiction', 'split'):
            benchmarks.set_gate(dataset_lock, gate, **stamp)
        with self.assertRaisesRegex(ValueError, 'stale: dataset.lock.json'):
            contracts.load_suite(lock)      # the gate state is pinned: a changed dataset lock needs a relock
        with self.assertRaisesRegex(ValueError, 'Dataset import gate is blocked: grader_parity$'):
            contracts.load_suite(relock(out))
        with self.assertRaisesRegex(ValueError, 'Grader parity needs a matching parity run'):
            benchmarks.set_gate(dataset_lock, 'grader_parity', **stamp)
        gold = AdapterTests.gold_ranges(out)
        wrong = [{'upstream_id': uid, 'retrieved': g, 'precision': 0.5, 'recall': 1.0} for uid, g in gold.items()]
        self.assertEqual(benchmarks.parity_check(dataset_lock, AdapterTests.native(out, wrong))['status'], 'mismatch')
        with self.assertRaisesRegex(ValueError, 'Grader parity needs a matching parity run'):
            benchmarks.set_gate(dataset_lock, 'grader_parity', **stamp)
        right = [{**example, 'precision': 1.0} for example in wrong]
        self.assertEqual(benchmarks.parity_check(dataset_lock, AdapterTests.native(out, right))['status'], 'match')
        benchmarks.set_gate(dataset_lock, 'grader_parity', **stamp)
        suite = contracts.load_suite(relock(out))
        self.assertEqual((suite['lock']['data_class'], benchmarks.blocked_gates(suite['dataset'])), ('public-benchmark', []))
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'The bytes gate is set by the import'):
                benchmarks.set_gate(dataset_lock, 'bytes', **stamp)
        with self.assertRaisesRegex(ValueError, 'Unknown dataset gate'):
            benchmarks.set_gate(dataset_lock, 'everything', **stamp)

    def test_edited_manifest_blocks_the_bytes_gate(self):
        out = AdapterTests.imported(self)
        AdapterTests.verify_all(out)
        contracts.load_suite(out / 'suite.lock.json')
        saved = {p: p.read_bytes() for p in out.rglob('*') if p.is_file()}

        def other_span(r):
            spans = [s['span_id'] for s in read_json(out / 'matters.json')['shared_sources'][0]['spans']]
            entry = r['matters'][0]
            entry['gold_spans'] = [next(s for s in spans if s not in entry['gold_spans'])]
        edit(out / 'rubric.json', other_span)
        with self.assertRaisesRegex(ValueError, 'Dataset import gate is blocked: bytes$'):
            contracts.load_suite(relock(out))
        for path, data in saved.items():
            path.write_bytes(data)
        copied = out / 'originals/privacy_qa/lantern.txt'
        copied.write_bytes(copied.read_bytes().replace(b'two years', b'ten years'))
        with self.assertRaisesRegex(ValueError, 'Dataset import gate is blocked: bytes$'):
            contracts.load_suite(relock(out))

    def test_imported_sources_are_anchored_to_pinned_copies(self):
        out = AdapterTests.imported(self)
        AdapterTests.verify_all(out)
        suite = contracts.load_suite(out / 'suite.lock.json')
        sources = suite['matters']['shared_sources']
        self.assertEqual(len(sources), 2)
        for s in sources:
            self.assertIn(s['original_sha256'], suite['originals'])
            self.assertEqual((s['parse']['status'], s['source_set'], s['excluded_matters']), ('ok', 'candidate', []))
            self.assertTrue(all(span['locator']['kind'] == 'text' for span in s['spans']))
            self.assertTrue(all(len(span['text']) <= 1000 for span in s['spans']))
        self.assertEqual(ingest.verify_anchors(suite), [])
        self.assertEqual((out / 'originals/privacy_qa/orchard.txt').read_bytes(), DOC_B.encode())      # byte for byte
        lock = read_json(out / 'suite.lock.json')
        self.assertEqual([e['path'] for e in lock['source_files'] if e['purpose'] == 'source'],
                         ['originals/privacy_qa/lantern.txt', 'originals/privacy_qa/orchard.txt'])
        pinned = [p.relative_to(out.resolve()).as_posix() for p in contracts.pinned_files(out / 'suite.lock.json')]
        self.assertEqual(pinned, ['matters.json', 'corpus.json', 'rubric.json', 'dataset.lock.json',
                                  'originals/privacy_qa/lantern.txt', 'originals/privacy_qa/orchard.txt'])
        view = contracts.candidate_view(suite)
        self.assertEqual([f['purpose'] for f in view['lock']['source_files']], ['matters', 'corpus'])
        saved = (out / 'suite.lock.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Source files need a collection or a dataset lock'):
            contracts.load_suite(relock(out, drop=('dataset_lock',)))
        (out / 'suite.lock.json').write_bytes(saved)
        edit(out / 'suite.lock.json', lambda l: l.update(data_class='public-synthetic'))
        with self.assertRaisesRegex(ValueError, 'A dataset lock belongs to a public-benchmark suite'):
            contracts.load_suite(out / 'suite.lock.json')

    def test_malformed_or_tampered_dataset_lock_is_rejected(self):
        out = AdapterTests.imported(self)
        good = benchmarks.verify_dataset(out / 'dataset.lock.json')
        self.assertIs(benchmarks.validate_dataset(good), good)
        cases = {
            'Unknown fields': lambda d: d.update(notes='free text'),
            'Missing fields: grader_parity': lambda d: d['gates'].pop('grader_parity'),
            'gate evidence must be an identifier-like string': lambda d: d['gates']['license'].update(status='verified', verified_by='operator-a',
                                                                                                     verified_utc='2026-11-12T00:00:00Z'),
            'gate verified_by must be an identifier-like string': lambda d: d['gates']['license'].update(
                status='verified', evidence='check-1', verified_by='Jane Doe checked it', verified_utc='2026-11-12T00:00:00Z'),
            'UTC timestamp': lambda d: d['gates']['license'].update(status='verified', evidence='check-1', verified_by='a', verified_utc='yesterday'),
            'A blocked gate records no verification': lambda d: d['gates']['split'].update(evidence='check-1'),
            'upstream origin': lambda d: d['upstream'].update(origin='somewhere on the web'),
            'files must be sorted': lambda d: d['files'].reverse(),
            'Every example is imported, rejected or missing': lambda d: d['examples'].update(total=9, upstream_total=9),
            'Unknown dataset adapter': lambda d: d.update(adapter='scraped-copy'),
            'A parity check that was not run records no result': lambda d: d['parity'].update(scorer='x@1'),
            'Suite path escapes the lock directory': lambda d: d['files'][0].update(path='../benchmarks/privacy_qa.json'),
        }
        for message_text, change in cases.items():
            with self.subTest(message=message_text):
                value = copy.deepcopy(good)
                change(value)
                with self.assertRaisesRegex(ValueError, message_text):
                    benchmarks.validate_dataset(value)
        text = (out / 'dataset.lock.json').read_text(encoding='utf-8')
        (out / 'dataset.lock.json').write_text(text.replace('"split": "mini",', '"split": "mini",\n  "split": "full",', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key: split'):
            benchmarks.verify_dataset(out / 'dataset.lock.json')
        dump(out / 'dataset.lock.json', good)
        AdapterTests.verify_all(out)
        contracts.load_suite(out / 'suite.lock.json')
        edit(out / 'dataset.lock.json', lambda d: d['gates']['license'].update(status='blocked', evidence=None, verified_by=None, verified_utc=None))
        with self.assertRaisesRegex(ValueError, 'stale: dataset.lock.json'):
            contracts.load_suite(out / 'suite.lock.json')
        with self.assertRaisesRegex(ValueError, 'blocked: license$'):
            contracts.load_suite(relock(out))
        edit(out / 'dataset.lock.json', lambda d: (d['gates']['license'].update(status='verified', evidence='x', verified_by='y',
                                                                                verified_utc='2026-11-12T00:00:00Z'),
                                                   d['parity'].update(status='mismatch')))
        with self.assertRaisesRegex(ValueError, 'blocked: grader_parity$'):
            contracts.load_suite(relock(out))      # a hand-edited gate without a matching parity run stays blocked
        edit(out / 'dataset.lock.json', lambda d: d.update(gates='all verified'))
        with self.assertRaisesRegex(ValueError, 'Expected an object|Malformed'):
            contracts.load_suite(relock(out))

    def test_a_matching_parity_record_must_be_consistent(self):
        out = AdapterTests.imported(self)
        AdapterTests.verify_all(out)
        good = benchmarks.verify_dataset(out / 'dataset.lock.json')
        rubric = read_json(out / 'rubric.json')
        self.assertIs(benchmarks.validate_dataset(good, rubric=rubric), good)
        row = good['parity']['sample'][0]

        def unknown(d):
            d['parity']['sample'][0]['upstream_id'] = 'privacy_qa:99'

        def outside(d):
            d['parity']['sample'][0].update(native_precision=d['parity']['sample'][0]['local_precision'] - 0.5, difference=0.5)
            d['parity']['max_abs_difference'] = 0.5

        def maximum(d):
            d['parity']['max_abs_difference'] = 0.25

        def forged_row(d):      # reviewer probe p10 A2: a row whose own difference contradicts its values
            d['parity']['sample'][0].update(local_precision=0.0, local_recall=0.0, native_precision=1.0, native_recall=1.0, difference=0.0)

        def no_native(d):
            d['parity']['sample'][0].update(native_recall=None)

        def wrong_flag(d):
            d['parity']['sample'][0].update(precision_denominator_empty=True)
        cases = [(unknown, 'parity sample names an example that is not in the import: privacy_qa:99', True),
                 (outside, 'A matching parity record differs beyond the tolerance', False),
                 (maximum, 'max_abs_difference must be the largest sample difference', False),
                 (lambda d: d['parity']['sample'][0].pop('difference'), 'Missing fields: difference', False),
                 (forged_row, 'A parity sample row disagrees with its own values: ' + row['upstream_id'], False),
                 (no_native, 'A parity sample row needs a native value for every compared metric: ' + row['upstream_id'], False),
                 (wrong_flag, 'A parity sample row disagrees with its own values: ' + row['upstream_id'], False)]
        for change, message_text, needs_rubric in cases:
            with self.subTest(message=message_text):
                value = copy.deepcopy(good)
                change(value)
                with self.assertRaisesRegex(ValueError, message_text):
                    benchmarks.validate_dataset(value, rubric=rubric if needs_rubric else None)
        self.assertEqual(set(row), {'upstream_id', 'local_precision', 'local_recall', 'native_precision', 'native_recall', 'difference',
                                    'precision_denominator_empty', 'recall_denominator_empty'})
        # Reviewer probe p4 case A: every gate hand-set to verified with a forged parity record, then relocked.
        verified = {'status': 'verified', 'evidence': 'x', 'verified_by': 'y', 'verified_utc': '2026-01-01T00:00:00Z'}
        edit(out / 'dataset.lock.json', lambda d: (d['gates'].update({g: dict(verified) for g in benchmarks.GATES}),
                                                   d['parity'].update(scorer='fake@1', status='match', max_abs_difference=0.9,
                                                                      sample=[{**row, 'upstream_id': 'nothing-real', 'difference': 0.9}])))
        with self.assertRaisesRegex(ValueError, 'not in the import|beyond the tolerance|disagrees with its own values'):
            contracts.load_suite(relock(out))
        # Reviewer probe p10 A2: a well-formed row of a real example, local 0 against native 1, recorded as difference 0.
        forged = {**row, 'local_precision': 0.0, 'local_recall': 0.0, 'native_precision': 1.0, 'native_recall': 1.0, 'difference': 0.0}
        edit(out / 'dataset.lock.json', lambda d: d['parity'].update(scorer='fake@1', status='match', max_abs_difference=0.0, sample=[forged]))
        with self.assertRaisesRegex(ValueError, 'A parity sample row disagrees with its own values'):
            contracts.load_suite(relock(out))

    def test_imported_sources_exclude_no_matter(self):
        out = AdapterTests.imported(self)
        AdapterTests.verify_all(out)
        first = read_json(out / 'matters.json')['matters'][0]['matter_id']
        edit(out / 'matters.json', lambda m: m['shared_sources'][0].update(excluded_matters=[first]))
        edit(out / 'dataset.lock.json', lambda d: next(x for x in d['derived'] if x['path'] == 'matters.json').update(
            sha256=sha256_file(out / 'matters.json')))
        with self.assertRaisesRegex(ValueError, 'An imported source excludes no matter: ' + read_json(out / 'matters.json')['shared_sources'][0]['source_id']):
            contracts.load_suite(relock(out))


class PacketSuiteTests(unittest.TestCase):
    def test_shipped_packet_suite_loads_and_anchors_verify(self):
        suite = contracts.load_suite(PACKETS / 'suite.lock.json')
        self.assertEqual(ingest.verify_anchors(suite), [])
        fixture.check_gold(suite)
        lock = suite['lock']
        self.assertEqual((lock['benchmark_id'], lock['split_id'], lock['data_class'], lock['revision']),
                         ('legal-original-packets', 'calibration', 'public-synthetic', '2026-11-11.1'))
        families = {}
        for m in suite['matters']['matters']:
            families.setdefault(m['family_id'], []).append(m['matter_id'])
        self.assertEqual(families, {'p1-quay': ['p1-quay-a', 'p1-quay-b'], 'p2-kiln': ['p2-kiln-a', 'p2-kiln-b']})
        [note] = suite['review']['sources']
        self.assertEqual((note['source_set'], note['matter_id']), ('review', 'p2-kiln-a'))
        view = contracts.candidate_view(suite)
        text = json.dumps(view, ensure_ascii=False)
        for span in note['spans']:
            self.assertNotIn(span['text'], text)
        self.assertNotIn(note['source_id'], text)
        self.assertEqual([f['purpose'] for f in view['lock']['source_files']], ['matters', 'corpus'])
        gold = {g['matter_id']: g for g in suite['rubric']['matters']}
        for matter in suite['matters']['matters']:      # the reference pipeline passes every criterion here too
            criteria = fixture.score(fixture.draft(matter, view['corpus']), matter, gold[matter['matter_id']], suite['corpus'])
            self.assertTrue(all(criteria.values()), (matter['matter_id'], criteria))
        # Family 1: a byte-identical report and an email that differs only in its dates; family 2: the email attachment
        # supplies the missing element.
        p1 = {m['matter_id']: m['sources'] for m in suite['matters']['matters']}
        self.assertEqual(p1['p1-quay-a'][0]['original_sha256'], p1['p1-quay-b'][0]['original_sha256'])
        a_mail, b_mail = ((PACKETS / f'raw/{m}/thread.eml').read_text(encoding='utf-8').splitlines() for m in ('p1-a', 'p1-b'))
        self.assertEqual([i for i, (x, y) in enumerate(zip(a_mail, b_mail)) if x != y], [3, 15])      # the Date header and the attribution
        self.assertEqual(len(a_mail), len(b_mail))
        self.assertEqual([s['text'] for s in p1['p1-quay-a'][1]['spans'][:3]], [s['text'] for s in p1['p1-quay-b'][1]['spans'][:3]])
        attachment = next(s for s in p1['p2-kiln-b'] if s['parent_source_id'])
        # sent before the operative date, the register states only that no permit was issued, not that the kiln was fired
        self.assertNotIn('fired', ' '.join(span['text'] for span in attachment['spans']))
        self.assertEqual(gold['p2-kiln-b']['evidence_spans']['no-permit']['support'], [attachment['spans'][1]['span_id']])
        self.assertTrue(any(span.get('quoted') for s in p1['p1-quay-a'] for span in s['spans']))
        [brief] = [s for s in suite['matters']['shared_sources'] if s['role'] == 'prior_brief']
        self.assertEqual(brief['excluded_matters'], ['p1-quay-a', 'p1-quay-b'])

    def test_no_source_date_follows_the_operative_date(self):
        for lock in sorted((X / 'workloads').glob('*/suite.lock.json')):
            view = contracts.candidate_view(contracts.load_suite(lock))
            for matter in view['matters']['matters']:
                for source in matter['sources']:
                    date = (source.get('email') or {}).get('date')
                    with self.subTest(suite=lock.parent.name, matter=matter['matter_id'], source=source['source_id']):
                        if date is not None:
                            self.assertLessEqual(date[:10], matter['operative_date'])
        dates = {m['matter_id']: [s['email']['date'] for s in m['sources'] if s.get('email')]
                 for m in contracts.load_suite(PACKETS / 'suite.lock.json')['matters']['matters']}
        self.assertEqual(sorted(k for k, v in dates.items() if v), ['p1-quay-a', 'p1-quay-b', 'p2-kiln-b'])      # the check is not vacuous

    def test_reingesting_the_raw_files_reproduces_the_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / 'packets'
            shutil.copytree(PACKETS, copy_dir)
            for name in ('matters.json', 'corpus.json', 'review.json', 'ingest-report.json'):
                (copy_dir / name).unlink()
            report = ingest.ingest_collection(copy_dir / 'collection.json', copy_dir / 'visibility.json', copy_dir)
            for name in ('matters.json', 'corpus.json', 'review.json', 'ingest-report.json'):
                self.assertEqual((copy_dir / name).read_bytes(), (PACKETS / name).read_bytes(), name)
            self.assertEqual({e['status'] for e in report['files']}, {'ok'})
            self.assertEqual(ingest.lock_suite(copy_dir, benchmark_id='legal-original-packets', revision='2026-11-11.1',
                                               split_id='calibration').read_bytes(), (PACKETS / 'suite.lock.json').read_bytes())

    def test_collection_passes_policy_and_authority_metadata_through(self):
        collection, corpus = read_json(PACKETS / 'collection.json'), read_json(PACKETS / 'corpus.json')
        self.assertEqual((corpus['policy'], corpus['availability_cutoff']), (collection['policy'], collection['availability_cutoff']))
        self.assertEqual(set(corpus['policy']), {'policy_id', 'version', 'jurisdiction', 'effective_from_inclusive', 'effective_to_inclusive',
                                                 'require_status_as_of', 'postures', 'binding_courts', 'review'})
        declared = {(f['authority']['authority_id'], f['authority']['version']): f for f in collection['files'] if f['namespace'] == 'authority'}
        self.assertEqual(len(declared), 4)
        self.assertEqual(sorted(declared), [(a['authority_id'], a['version']) for a in corpus['authorities']])
        for a in corpus['authorities']:
            f = declared[(a['authority_id'], a['version'])]
            self.assertEqual({k: v for k, v in a.items() if k not in ('text', 'text_sha256', 'original_sha256')}, f['authority'])
            self.assertEqual(a['original_sha256'], sha256_file(PACKETS / f['path']))
            self.assertLessEqual(a['snapshot']['published'], corpus['availability_cutoff'])
            self.assertIsNotNone(a['status_as_of'])
            if a['status'] in ('superseded', 'repealed'):
                self.assertIsNotNone(a['effective_to'])
            self.assertNotEqual(a['status'], 'invalidated')
        persuasive = [a for a in corpus['authorities'] if a.get('weight') == 'persuasive']
        self.assertEqual(len(persuasive), 1)
        gold = read_json(PACKETS / 'rubric.json')['matters']
        key = [persuasive[0]['authority_id'], persuasive[0]['version']]
        self.assertTrue(all(g['controlling_authority'] != key and key not in g['established_exemptions'] for g in gold))
        self.assertTrue(all(m['operative_date'] <= corpus['availability_cutoff'] for m in collection['matters']))
        self.assertEqual(len({a['citation'] for a in corpus['authorities'] if a['authority_id'] == 'vho-9-2'}), 1)

    def test_packet_suite_is_a_separate_split(self):
        packets, smoke = contracts.load_suite(PACKETS / 'suite.lock.json'), contracts.load_suite(SMOKE / 'suite.lock.json')
        self.assertEqual(packets['lock']['split_id'], 'calibration')
        self.assertNotEqual(packets['lock']['split_id'], smoke['lock']['split_id'])
        for key in ('family_id', 'question'):
            self.assertFalse({m[key] for m in packets['matters']['matters']} & {m[key] for m in smoke['matters']['matters']}, key)
        self.assertFalse({a['authority_id'] for a in packets['corpus']['authorities']} & {a['authority_id'] for a in smoke['corpus']['authorities']})
        self.assertFalse({a['citation'] for a in packets['corpus']['authorities']} & {a['citation'] for a in smoke['corpus']['authorities']})

    def test_smoke_suite_and_its_lock_are_unchanged(self):
        self.assertIn(sha256_file(SMOKE / 'suite.lock.json'), contracts.approved_suites())
        suite = contracts.load_suite(SMOKE / 'suite.lock.json')
        self.assertEqual([p.name for p in contracts.pinned_files(SMOKE / 'suite.lock.json')], ['matters.json', 'corpus.json', 'rubric.json'])
        self.assertEqual({k: suite[k] for k in ('collection', 'visibility', 'oracle', 'review', 'dataset', 'originals')},
                         {'collection': None, 'visibility': None, 'oracle': None, 'review': None, 'dataset': None, 'originals': {}})
        self.assertEqual(ingest.verify_anchors(suite), [])


if __name__ == '__main__':
    unittest.main()
