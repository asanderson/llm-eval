"""Bounded offline ingestion of raw matter files into suite manifests, as an explicit operator step.

`python -m llm_eval.experiments.legal_benchmark.ingest --collection DIR/collection.json --visibility DIR/visibility.json
--output DIR [--lock --benchmark-id ID --revision REV --split-id ID]`

Raw files are untrusted content. Nothing here fetches, executes or expands anything: UTF-8 text and `.eml` are parsed
with the standard library, an attachment name only selects a parser by its extension and is never used as a path,
archives are not expanded, HTML is reduced to text without loading what it references, and DOCX or PDF text is
extracted only by a backend pinned in `experiments/legal-benchmark/capabilities.json`. Content problems become report
statuses, never exceptions; the planner never calls this module, it only reads and hashes what it produced.
"""
from __future__ import annotations

import argparse
import datetime
import email
import email.policy
import email.utils
import hashlib
import html
import html.parser
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

from llm_eval.common import sha256_file
from llm_eval.core.contracts import fields, identifier

from . import contracts

ROOT = Path(__file__).resolve().parents[4]
CAPABILITIES = 'experiments/legal-benchmark/capabilities.json'
LIMITS = {'max_file_bytes': 8 * 1024 * 1024, 'max_files': 2000, 'max_total_bytes': 256 * 1024 * 1024,
          'max_attachment_depth': 3, 'max_spans_per_source': 2000, 'max_span_chars': 2000,
          # Header parsing is not linear in the header size: an email is refused before it is parsed above these.
          'max_header_bytes': 64 * 1024, 'max_header_line_bytes': 8 * 1024, 'max_parts': 500}
OPTIONAL_CAPABILITIES = ('pdf', 'docx', 'ocr')
CAPABILITY_KEYS = ('module', 'distribution', 'version', 'callable')
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
MEDIA_TYPES = {'.txt': 'text/plain', '.eml': 'message/rfc822', '.pdf': 'application/pdf', '.docx': DOCX,
               '.docm': 'application/vnd.ms-word.document.macroenabled.12'}
EXTENSIONS = {'text/plain': '.txt', 'message/rfc822': '.eml', 'application/pdf': '.pdf', DOCX: '.docx'}
ARCHIVES = ('.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar')
# Names ingestion writes or reads in the suite directory: a collected file may not take one of them.
SUITE_FILES = ('matters.json', 'corpus.json', 'rubric.json', 'oracle.json', 'review.json', 'collection.json', 'visibility.json',
               'ingest-report.json', 'suite.lock.json')
SOURCE_ORDER = ('source_id', 'role', 'version', 'kind', 'original_sha256', 'original_bytes', 'media_type', 'parent_source_id',
                'attachments', 'email', 'parse', 'source_set', 'excluded_matters', 'spans')
CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f]')
SURROGATE = re.compile('[\ud800-\udfff]')
SENTENCE_END = re.compile(r'[.!?](?=\s)')
QUOTE_START = re.compile(r'On .+ wrote:|-----Original Message-----')
MARKDOWN = frozenset('\\`*_{}[]()#+-!|~@')      # `@`: GFM turns an email address or mailto: into a link
# Line and paragraph separators, bidirectional marks, embeddings, overrides and isolates, the byte order mark,
# next line, vertical tab and form feed.
INVISIBLE = re.compile('[\u2028\u2029\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c\ufeff\u0085\x0b\x0c]')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _extension(name):
    """Lower-cased extension of an untrusted name: it selects a parser and nothing else."""
    base = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    return PurePosixPath(base).suffix.lower() if base not in ('', '.', '..') else ''


def _capabilities(root):
    try:
        value, digest = contracts.read_json_strict(Path(root or ROOT) / CAPABILITIES)
    except (OSError, ValueError):
        return {}, None
    pins = value.get('capabilities') if isinstance(value, dict) else None
    return (pins if isinstance(pins, dict) else {}), digest


def capability(name, root=None):
    """`text` and `eml` always; `pdf`, `docx`, `ocr` only when capabilities.json pins module, distribution, exact version
    and callable, the module can be found and the installed distribution has exactly the pinned version."""
    if name in ('text', 'eml'):
        return True
    if name not in OPTIONAL_CAPABILITIES:
        return False
    pin = _capabilities(root)[0].get(name)
    if not isinstance(pin, dict) or any(not isinstance(pin.get(key), str) or not pin[key] for key in CAPABILITY_KEYS):
        return False
    try:
        if importlib.util.find_spec(pin['module']) is None:
            return False
        return importlib.metadata.version(pin['distribution']) == pin['version']
    except (ImportError, ValueError):      # PackageNotFoundError is an ImportError
        return False


def extractor(name, root=None):
    """The pinned extractor callable, or None. Never a fallback."""
    if not capability(name, root):
        return None
    pin = _capabilities(root)[0][name]
    try:
        function = getattr(importlib.import_module(pin['module']), pin['callable'], None)
    except ImportError:
        return None
    return function if callable(function) else None


def source_id(namespace, original_sha256, part='', matter_id=''):
    """Deterministic opaque id of one source: namespace, owning matter and the digest of its own decoded bytes."""
    key = namespace + '\0' + matter_id + '\0' + original_sha256 + '\0' + part
    return 's-' + hashlib.sha256(key.encode()).hexdigest()[:16]


def escape(text):
    """Untrusted text for one Markdown rendering (which also produces HTML): on one line, invisible separators and bidi
    controls replaced by U+FFFD, Markdown punctuation backslashed, autolinks and a leading list number broken, then
    HTML-escaped, so that entities stay valid. One rendering pass shows the text as written; callers must not escape twice."""
    text = INVISIBLE.sub('\ufffd', text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' '))
    text = ''.join('\\' + c if c in MARKDOWN else c for c in text)
    text = re.sub(r'(?i)\bwww\.', lambda m: m.group(0)[:-1] + '\\.', text.replace('://', ':\\/\\/'))
    text = re.sub(r'^(\d{1,9})\.', r'\1\\.', text)
    text = html.escape(text, quote=True)
    # Leading spaces or tabs would open an indented code block: they are written as character references.
    return re.sub(r'^[ \t]+', lambda m: ''.join('&#32;' if c == ' ' else '&#9;' for c in m.group(0)), text)


def _normalise(text):
    """LF line endings; control characters other than newline and tab, and undecodable surrogates, become U+FFFD."""
    reasons = set()
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if CONTROL.search(text):
        text, reasons = CONTROL.sub('\ufffd', text), {'control_characters_replaced'}
    if SURROGATE.search(text):
        text = SURROGATE.sub('\ufffd', text)
        reasons.add('undecodable_characters_replaced')
    return text, reasons


def _trim(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _cut(text, start, end, limit):
    """(start, end) pieces of one paragraph of at most `limit` characters, cut at the last sentence end before the limit."""
    pieces = []
    start, end = _trim(text, start, end)
    while start < end:
        if end - start <= limit:
            pieces.append((start, end))
            break
        cut = max((m.end() for m in SENTENCE_END.finditer(text, start, start + limit)), default=start)
        stop = cut if cut > start else start + limit
        piece = _trim(text, start, stop)
        if piece[1] > piece[0]:
            pieces.append(piece)
        start = _trim(text, stop, end)[0]
    return pieces


def _segments(text, quoted=None, limit=None):
    """[(start, end, quoted)]: runs of non-blank lines with one quoted flag, each cut to at most `limit` characters."""
    limit = limit or LIMITS['max_span_chars']
    paragraphs, current, position = [], None, 0
    for index, line in enumerate(text.split('\n')):
        start, end = position, position + len(line)
        position = end + 1
        flag = bool(quoted[index]) if quoted else False
        if not line.strip():
            current = None
        elif current is not None and current[2] == flag:
            current[1] = end
        else:
            current = [start, end, flag]
            paragraphs.append(current)
    return [(s, e, flag) for start, end, flag in paragraphs for s, e in _cut(text, start, end, limit)]


def _quoted(text):
    """Quoted flag per line: lines starting with `>`, and everything from an attribution or original-message line on."""
    flags, after = [], False
    for line in text.split('\n'):
        if QUOTE_START.fullmatch(line.rstrip()):
            after = True
        flags.append(after or line.startswith('>'))
    return flags


class _HTMLText(html.parser.HTMLParser):
    """Text of an HTML body without script or style content. A `src` or `href` is recorded, never loaded."""
    BLOCKS = frozenset('p div li tr table ul ol blockquote h1 h2 h3 h4 h5 h6 pre section article header footer title noscript'.split())
    HIDDEN = frozenset(('script', 'style', 'template'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.external = [], 0, False

    def handle_starttag(self, tag, attrs):
        if any(name in ('src', 'href') for name, _ in attrs):
            self.external = True
        if tag in self.HIDDEN:
            self.skip += 1
        elif tag == 'br':
            self.parts.append('\n')
        elif tag in self.BLOCKS:
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_text(markup):
    parser = _HTMLText()
    parser.feed(markup)
    parser.close()
    return ''.join(parser.parts), parser.external


def _header(message, name):
    try:
        value = message.get(name)
        value = None if value is None else _normalise(str(value))[0].strip()
    except Exception:      # a malformed header is content: it is treated as absent
        return None
    return value or None


def _raw_header(message, name):
    """The first header `name` as written (unfolded), without the policy reformatting it: a parsed date header would print
    its year with a century already added."""
    for key, value in message.raw_items():
        if key.lower() == name.lower():
            return ' '.join(_normalise(str(value))[0].split()) or None
    return None


def _year_token(raw):
    """The year as written in a date header: the last all-digit token, with whitespace, commas or the dashes of `02-May-25`
    as separators, so day-month and month-day order give the same token. Times and zones are not all-digit; comments are
    dropped. None when the header has no such token."""
    tokens = []
    for token in re.split(r'[\s,]+', re.sub(r'\([^)]*\)', ' ', raw)):
        tokens += token.split('-') if re.fullmatch(r'\d{1,2}-[A-Za-z]+-\d+', token) else [token]
    digits = [token for token in tokens if token.isdigit() and token.isascii()]
    return digits[-1] if digits else None


def _email_date(message):
    """(UTC ISO 8601 or None, reason or None). A value without a zone is never converted: that would use the zone of the host."""
    raw = _raw_header(message, 'Date')
    if raw is None:
        return None, 'bad_date'
    year = _year_token(raw)
    if year is not None and (len(year) != 4 or int(year) < 1900):      # a year is never given a century
        return None, 'bad_date'
    try:
        value = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None, 'bad_date'
    if value is None or value.year < 1900:
        return None, 'bad_date'
    if value.tzinfo is None:
        return None, 'date_without_zone'
    try:
        return value.astimezone(datetime.timezone.utc).isoformat(), None
    except (ValueError, OverflowError):      # outside the range of datetime after the conversion
        return None, 'bad_date'


class _Refused(Exception):
    """Content that is refused before it is parsed further; the argument is the reason code."""


def _header_block_too_large(data):
    """True when the raw header block (bytes up to the first blank line) or one unfolded header in it is above the limits.
    Checked on bytes, before any parsing: parsing a header is not linear in its size."""
    if data.startswith((b'\r\n', b'\n')):
        return False
    ends = [i for i in (data.find(b'\r\n\r\n'), data.find(b'\n\n')) if i >= 0]
    block = data[:min(ends)] if ends else data
    if len(block) > LIMITS['max_header_bytes']:
        return True
    longest = current = 0
    for line in block.splitlines():
        current = current + len(line) if line[:1] in (b' ', b'\t') else len(line)
        longest = max(longest, current)
    return longest > LIMITS['max_header_line_bytes']


def _headers_too_large(part):
    """The same limits on the headers of one MIME part, read raw (without the policy parsing them)."""
    sizes = [len(name) + 2 + len(value) for name, value in part.raw_items()]
    return sum(sizes) > LIMITS['max_header_bytes'] or any(size > LIMITS['max_header_line_bytes'] for size in sizes)


def _lean_check(message):
    """On a message parsed with `compat32` (no structured headers): refuse oversized headers of every part, and of the
    Content-Type of every part inside a nested message (the structured parse reads it to find boundaries); count the parts
    in walk() order and cut the tree after `max_parts`. Returns True when parts were cut. Runs before any structured parse."""
    counter, truncated = [0], [False]

    def visit(part, inside):
        counter[0] += 1
        if _headers_too_large(part) if not inside else \
                any(len(name) + 2 + len(value) > LIMITS['max_header_line_bytes'] for name, value in part.raw_items()
                    if name.lower() == 'content-type'):
            raise _Refused('header_too_large')
        if not part.is_multipart() or not isinstance(part.get_payload(), list):
            return
        children, kept = part.get_payload(), []
        nested = inside or part.get_content_type() == 'message/rfc822'
        for child in children:
            if counter[0] >= LIMITS['max_parts']:
                truncated[0] = True
                break
            kept.append(child)
            visit(child, nested)
        if len(kept) < len(children):
            part.set_payload(kept)
    visit(message, False)
    return truncated[0]


def _layout(message):
    """(body text parts, attachment parts, truncated) as [(1-based index in message.walk() order, part)]. Attachment
    subtrees are numbered as walk() numbers them but are not body text of this message. At most `max_parts` parts are
    walked (`truncated` is then true). Raises _Refused('header_too_large') for a part with oversized headers."""
    body, attachments, counter, truncated = [], [], [0], [False]

    def visit(part, inside):
        if counter[0] >= LIMITS['max_parts']:
            truncated[0] = True
            return
        counter[0] += 1
        index = counter[0]
        if not inside and _headers_too_large(part):      # a nested message's own headers are checked when it is ingested
            raise _Refused('header_too_large')
        children = part.get_payload() if part.is_multipart() else []
        if not inside:
            kind = part.get_content_type()
            if kind == 'message/rfc822' or (not part.is_multipart() and (part.get_content_disposition() == 'attachment' or part.get_filename())):
                attachments.append((index, part))
                inside = True
            elif part.is_multipart():
                pass
            elif kind in ('text/plain', 'text/html'):
                body.append((index, part))
            else:
                attachments.append((index, part))
        for child in children if isinstance(children, list) else []:
            visit(child, inside)
    visit(message, False)
    return body, attachments, truncated[0]


# The parser does not expose the original bytes of a nested message, so a nested message is re-serialised. Source headers
# are written as they were read (not refolded): that keeps it cheap, and its header block is then checked like any email.
NESTED_POLICY = email.policy.default.clone(refold_source='none')


def _attachment(part):
    """(decoded bytes, extension) of an attachment part. The file name only selects the parser."""
    if part.get_content_type() == 'message/rfc822':
        payload = part.get_payload()
        inner = payload[0] if isinstance(payload, list) and payload else None
        return (inner.as_bytes(policy=NESTED_POLICY) if inner is not None else b''), '.eml'
    data = part.get_payload(decode=True) or b''
    name = part.get_filename()
    return data, (_extension(name) if name else EXTENSIONS.get(part.get_content_type(), ''))


class _Run:
    """One ingestion pass: source records in order, report entries in order, and the ids already seen (duplicates)."""

    def __init__(self, root=None):
        self.root, self.seen, self.sources, self.entries = root, {}, [], []

    def entry(self, path, part, sha256, size, media_type, status, reasons=(), duplicate_of=None):
        self.entries.append({'path': path, 'part': part, 'sha256': sha256, 'bytes': size, 'media_type': media_type, 'status': status,
                             'reason_codes': sorted(set(reasons)), 'duplicate_of': duplicate_of})

    def add(self, data, *, path, part, ext, namespace, kind, matter_id, sender_roles, depth, parent):
        """Ingest one file or attachment. Returns its source id (also for a duplicate), or None when no record was made."""
        media_type = MEDIA_TYPES.get(ext, 'application/octet-stream')
        digest = _sha(data)
        sid = source_id(namespace, digest, '', matter_id)
        if sid in self.seen:
            self.entry(path, part, digest, len(data), media_type, 'duplicate', duplicate_of=sid)
            return sid
        if len(data) > LIMITS['max_file_bytes']:
            self.entry(path, part, digest, len(data), media_type, 'unsupported', ['too_large'])
            return None
        if ext == '.eml':
            return self._email(data, sid, digest, path=path, part=part, namespace=namespace, kind=kind, matter_id=matter_id,
                               sender_roles=sender_roles, depth=depth, parent=parent)
        try:
            status, reasons, spans, confidence, pages = self._parse(data, ext, sid)
        except Exception:      # an extractor or parser failure is a property of the content
            status, reasons, spans, confidence, pages = 'corrupt', {'parse_error'}, None, None, ([], [])
        self.entry(path, part, digest, len(data), media_type, status, reasons)
        if spans is None:
            return None
        self._record(sid, namespace, kind, digest, data, media_type, parent, status, reasons, spans, confidence, pages)
        return sid

    def _record(self, sid, namespace, kind, digest, data, media_type, parent, status, reasons, spans, confidence, pages, extra=None):
        record = {'source_id': sid, 'role': namespace, 'version': '1', 'kind': kind, 'original_sha256': digest, 'original_bytes': len(data),
                  'media_type': media_type, 'parent_source_id': parent, **(extra or {}),
                  'parse': {'status': status, 'confidence': confidence, 'missing_pages': pages[0], 'ocr_required_pages': pages[1],
                            'reason_codes': sorted(set(reasons))}, 'spans': spans}
        self.seen[sid] = record
        self.sources.append(record)
        return record

    def _spans(self, sid, text, segments, locate, quoted=None):
        spans = []
        for number, (start, end, flag) in enumerate(segments, 1):
            piece = text[start:end]
            span = {'span_id': f'{sid}#{number}', 'text': piece, 'text_sha256': contracts.text_digest(piece), 'locator': locate(start, end, number)}
            if quoted is not None:
                span['quoted'] = flag
            spans.append(span)
        return spans

    def _bounded(self, spans, reasons):
        if len(spans) > LIMITS['max_spans_per_source']:
            reasons.add('too_many_spans')
            return spans[:LIMITS['max_spans_per_source']], 'partial'
        return spans, 'ok'

    def _parse(self, data, ext, sid):
        """(status, reasons, spans or None, confidence, (missing_pages, ocr_required_pages)) of a non-email file."""
        none = ([], [])
        if ext == '.txt':
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                return 'corrupt', {'invalid_utf8'}, None, None, none
            text, reasons = _normalise(text[1:] if text.startswith('\ufeff') else text)
            segments = _segments(text)
            if not segments:
                return 'unsupported', {'no_text'}, None, None, none
            spans = self._spans(sid, text, segments, lambda s, e, n: {'kind': 'text', 'paragraph': n, 'start': s, 'end': e})
            spans, status = self._bounded(spans, reasons)
            return status, reasons, spans, 1.0, none
        if ext == '.pdf':
            return self._pdf(data, sid)
        if ext in ('.docx', '.docm'):
            return self._docx(data, ext, sid)
        if ext in ARCHIVES:
            return 'unsupported', {'archive_not_expanded'}, None, None, none
        return 'unsupported', {'unknown_type'}, None, None, none

    def _units(self, units, sid, locate, extra=lambda unit: {}):
        spans = []
        for unit in units:
            text, _ = _normalise(unit['text'] or '')
            for start, end in _cut(text, 0, len(text), LIMITS['max_span_chars']):
                piece = text[start:end]
                spans.append({'span_id': f'{sid}#{len(spans) + 1}', 'text': piece, 'text_sha256': contracts.text_digest(piece),
                              'locator': locate(unit), **extra(unit)})
        return spans

    def _pdf(self, data, sid):
        function = extractor('pdf', self.root)
        if function is None:
            return 'unsupported', {'capability_absent'}, None, None, ([], [])
        result = function(data)
        status = result.get('status') if isinstance(result, dict) else None
        if status in ('encrypted', 'corrupt'):
            return status, {status}, None, None, ([], [])
        pages, units = result.get('pages'), result.get('units') if status == 'ok' else None
        if type(pages) is not int or pages < 0 or not isinstance(units, list):
            return 'corrupt', {'extractor_output_invalid'}, None, None, ([], [])
        for unit in units:
            fields(unit, ['page', 'text', 'bbox', 'confidence'], ['page', 'text'])
            box, confidence = unit.get('bbox'), unit.get('confidence')
            if type(unit['page']) is not int or not 1 <= unit['page'] <= pages or not (unit['text'] is None or isinstance(unit['text'], str)) \
                    or not (box is None or (isinstance(box, list) and len(box) == 4 and all(type(x) in (int, float) for x in box))) \
                    or not (confidence is None or (type(confidence) in (int, float) and 0 <= confidence <= 1)):
                return 'corrupt', {'extractor_output_invalid'}, None, None, ([], [])
        seen = {u['page'] for u in units}
        missing = [page for page in range(1, pages + 1) if page not in seen]
        ocr = sorted({u['page'] for u in units if not (u['text'] or '').strip()})
        readable = sorted((u for u in units if (u['text'] or '').strip()), key=lambda u: u['page'])
        spans = self._units(readable, sid, lambda u: {'kind': 'pdf-page', 'page': u['page'], 'bbox': u.get('bbox')})
        reasons = ({'missing_pages'} if missing else set()) | ({'ocr_required'} if ocr else set())
        if not spans:
            return 'partial' if reasons else 'unsupported', reasons or {'no_text'}, None, None, (missing, ocr)
        spans, status = self._bounded(spans, reasons)
        confidences = [u['confidence'] for u in readable if u.get('confidence') is not None]
        return 'partial' if reasons else status, reasons, spans, (min(confidences) if confidences else None), (missing, ocr)

    def _docx(self, data, ext, sid):
        none = ([], [])
        if ext == '.docm':
            return 'unsupported', {'macro_content'}, None, None, none
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except (zipfile.BadZipFile, OSError, ValueError):
            return 'corrupt', {'bad_archive'}, None, None, none
        for name in names:      # names only: nothing is extracted or executed here
            parts = name.replace('\\', '/').split('/')
            if name.startswith(('/', '\\')) or re.match(r'[A-Za-z]:', name) or '..' in parts:
                return 'corrupt', {'archive_traversal'}, None, None, none
        if any(name.replace('\\', '/').lower() == 'word/vbaproject.bin' for name in names):
            return 'unsupported', {'macro_content'}, None, None, none
        function = extractor('docx', self.root)
        if function is None:
            return 'unsupported', {'capability_absent'}, None, None, none
        result = function(data)
        status = result.get('status') if isinstance(result, dict) else None
        if status in ('encrypted', 'corrupt'):
            return status, {status}, None, None, none
        units = result.get('units') if status == 'ok' else None
        if not isinstance(units, list):
            return 'corrupt', {'extractor_output_invalid'}, None, None, none
        for unit in units:
            fields(unit, ['section', 'paragraph', 'text', 'revision', 'comments'], ['section', 'paragraph', 'text'])
            comments = unit.get('comments') or []
            if any(type(unit[key]) is not int or unit[key] < 0 for key in ('section', 'paragraph')) or not isinstance(unit['text'], str) \
                    or unit.get('revision') not in (None, 'inserted', 'deleted') or not isinstance(comments, list) \
                    or any(not isinstance(c, str) or not c or len(c) > contracts.MAX_TEXT for c in comments):
                return 'corrupt', {'extractor_output_invalid'}, None, None, none
        readable = [u for u in units if u['text'].strip()]

        def extra(unit):
            keys = {}
            if unit.get('revision'):
                keys['revision'] = unit['revision']
            if unit.get('comments'):
                keys['comments'] = list(unit['comments'])
            return keys
        spans = self._units(readable, sid, lambda u: {'kind': 'docx-paragraph', 'section': u['section'], 'paragraph': u['paragraph']}, extra)
        if not spans:
            return 'unsupported', {'no_text'}, None, None, none
        reasons = set()
        spans, status = self._bounded(spans, reasons)
        return status, reasons, spans, 1.0, none

    def _parse_email(self, data, sid, sender_roles):
        if _header_block_too_large(data):
            raise _Refused('header_too_large')
        # The default policy parses structured headers (Content-Type of every part) while it parses the message, at a cost
        # that is not linear in their size. A compat32 pass parses none: the limits and the part cap are applied there first.
        lean = email.message_from_bytes(data, policy=email.policy.compat32)
        cut = _lean_check(lean)
        message = email.message_from_bytes(lean.as_bytes() if cut else data, policy=email.policy.default)
        body, attachments, truncated = _layout(message)
        truncated = truncated or cut
        reasons = {'too_many_parts'} if truncated else set()
        message_id = _header(message, 'Message-ID')
        message_id = message_id if message_id and len(message_id) <= contracts.MAX_TEXT else None
        references = (_header(message, 'References') or '').split()
        root = references[0] if references else (_header(message, 'In-Reply-To') or message_id)
        thread = 't-' + hashlib.sha256(root.encode('utf-8', 'replace')).hexdigest()[:12] if root else None
        sender = email.utils.parseaddr(_header(message, 'From') or '')[1].lower()
        date, problem = _email_date(message)
        if problem:
            reasons.add(problem)
        plain = [(i, p) for i, p in body if p.get_content_type() == 'text/plain']
        spans = []
        subject, subject_reasons = _normalise(_header(message, 'Subject') or '')
        reasons |= subject_reasons
        for start, end, _ in _segments(subject):
            spans.append((subject, 'subject', start, end, False))
        status = 'partial' if truncated else 'ok'
        for index, part in plain or [(i, p) for i, p in body if p.get_content_type() == 'text/html']:
            raw = part.get_payload(decode=True) or b''
            try:
                text = raw.decode(part.get_content_charset() or 'us-ascii')
            except (LookupError, UnicodeDecodeError):
                reasons.add('bad_charset')      # no guessed fallback: the part is skipped and the parse is partial
                status = 'partial'
                continue
            if part.get_content_type() == 'text/html':
                text, external = _html_text(text)
                if external:
                    reasons.add('external_reference')
            text, found = _normalise(text)
            reasons |= found
            for start, end, flag in _segments(text, _quoted(text)):
                spans.append((text, str(index), start, end, flag))
        records = []
        for text, part_name, start, end, flag in spans:
            piece = text[start:end]
            records.append({'span_id': f'{sid}#{len(records) + 1}', 'text': piece, 'text_sha256': contracts.text_digest(piece),
                            'locator': {'kind': 'email-body', 'part': part_name, 'start': start, 'end': end}, 'quoted': flag})
        records, bounded = self._bounded(records, reasons)
        info = {'message_id': message_id, 'thread_id': thread, 'sender_role': sender_roles.get(sender, 'unknown'), 'date': date}
        return ('partial' if bounded == 'partial' else status), reasons, records, info, attachments

    def _email(self, data, sid, digest, *, path, part, namespace, kind, matter_id, sender_roles, depth, parent):
        media_type = MEDIA_TYPES['.eml']
        try:
            status, reasons, spans, info, attachments = self._parse_email(data, sid, sender_roles)
        except _Refused as refusal:
            self.entry(path, part, digest, len(data), media_type, 'unsupported', [str(refusal)])
            return None
        except Exception:
            self.entry(path, part, digest, len(data), media_type, 'corrupt', ['parse_error'])
            return None
        record = None
        if not spans:      # its attachments are still walked, so each of them is reported
            self.entry(path, part, digest, len(data), media_type, 'unsupported', reasons | {'no_text'})
        else:
            self.entry(path, part, digest, len(data), media_type, status, reasons)
            record = self._record(sid, namespace, kind, digest, data, media_type, parent, status, reasons, spans, 1.0, ([], []),
                                  extra={'attachments': [], 'email': info})
        for index, child in attachments:
            child_part = f'{part}.{index}' if part else str(index)
            try:
                payload, ext = _attachment(child)
            except Exception:
                self.entry(path, child_part, _sha(b''), 0, 'application/octet-stream', 'corrupt', ['parse_error'])
                continue
            if depth + 1 > LIMITS['max_attachment_depth']:
                self.entry(path, child_part, _sha(payload), len(payload), MEDIA_TYPES.get(ext, 'application/octet-stream'), 'unsupported',
                           ['nesting_too_deep'])
                continue
            child_id = self.add(payload, path=path, part=child_part, ext=ext, namespace=namespace,
                                kind='message' if ext == '.eml' else 'attachment', matter_id=matter_id, sender_roles=sender_roles,
                                depth=depth + 1, parent=sid if record is not None else None)
            if record is not None and child_id is not None and child_id not in record['attachments']:
                record['attachments'].append(child_id)
        return sid if record is not None else None


def _roles(sender_roles):
    return {str(address).lower(): role for address, role in (sender_roles or {}).items()}


def ingest_bytes(data, *, name, namespace, kind, matter_id='', sender_roles=None, root=None, depth=0):
    """(source records, report entries) of one file: the file itself and, for email, its attachments. Never raises on
    content, never writes, fetches, executes or expands anything."""
    run = _Run(root)
    run.add(bytes(data), path=name, part='', ext=_extension(name), namespace=namespace, kind=kind, matter_id=matter_id,
            sender_roles=_roles(sender_roles), depth=depth, parent=None)
    return run.sources, run.entries


def _wrong(f):
    return ValueError('Wrong role assignment: ' + str(f.get('path') if isinstance(f, dict) else f))


_relative = contracts._relative      # the one validator of a suite-relative path


AUTHORITY_TYPES = {'authority_id': str, 'version': str, 'citation': str, 'title': str, 'issuer': str, 'authority_type': str, 'venues': list,
                   'effective_from': str, 'effective_to': (str, type(None)), 'status': str, 'pinpoint': str, 'elements': list}
OPTIONAL_AUTHORITY_TYPES = {'relates_to': str, 'jurisdiction': str, 'court': (str, type(None)), 'weight': str, 'aliases': list,
                            'snapshot': (dict, type(None)), 'status_as_of': (str, type(None)), 'review': (dict, type(None))}


def validate_collection(collection, directory=None):
    """Collection manifest v1: closed key sets, safe paths (beneath `directory` when given), limits and namespace rules.
    The authority object is checked for JSON types only; its meaning belongs to the corpus validation at load."""
    names = ['schema_version', 'data_class', 'jurisdiction_profile', 'venues', 'matters', 'files']
    fields(collection, names + ['policy', 'availability_cutoff'], names)
    contracts._version(collection['schema_version'], 'Unsupported collection manifest version')
    if collection['data_class'] not in contracts.DATA_CLASSES:
        raise ValueError('Unknown suite data_class')
    identifier(collection['jurisdiction_profile'])
    venues = contracts._unique([identifier(v) for v in contracts._strings(collection['venues'], 'venues')], 'venue')
    if 'policy' in collection and not isinstance(collection['policy'], dict):
        raise ValueError('The collection policy must be an object')
    if 'availability_cutoff' in collection:
        contracts.iso_date(collection['availability_cutoff'], 'availability_cutoff')
    if not isinstance(collection['matters'], list) or not isinstance(collection['files'], list):
        raise ValueError('A collection needs lists of matters and files')
    matters = set()
    for m in collection['matters']:
        keys = ['matter_id', 'family_id', 'operative_date', 'venue', 'posture', 'question', 'output_schema']
        fields(m, keys, keys)
        identifier(m['matter_id']); identifier(m['family_id']); contracts.iso_date(m['operative_date'], 'operative_date')
        if m['matter_id'] in matters:
            raise ValueError('Duplicate matter: ' + m['matter_id'])
        matters.add(m['matter_id'])
        if m['venue'] not in venues:
            raise ValueError('Matter names an undeclared venue: ' + m['matter_id'])
        if not isinstance(m['posture'], str) or m['posture'] not in contracts.POSTURES or m['output_schema'] != contracts.POSTURES[m['posture']]:
            raise ValueError('Unsupported posture or output schema')
        contracts._text(m['question'], 'A matter question')
    if len(collection['files']) > LIMITS['max_files']:
        raise ValueError(f"A collection lists at most {LIMITS['max_files']} files")
    paths, folded, versions = set(), set(), set()
    for f in collection['files']:
        fields(f, ['path', 'namespace', 'matter_id', 'kind', 'version', 'sender_roles', 'authority'], ['path', 'namespace'])
        _relative(f['path'])
        if directory is not None:
            contracts._inside(Path(directory).resolve(), f['path'])
        if f['path'] in paths or f['path'].casefold() in folded:      # a case variant names the same file on Windows
            raise ValueError('Duplicate collected file: ' + f['path'])
        paths.add(f['path'])
        folded.add(f['path'].casefold())
        if f['path'] in SUITE_FILES:
            raise ValueError('A collected file may not be a suite manifest: ' + f['path'])
        if f['namespace'] not in contracts.SOURCE_ROLES:
            raise ValueError('Unknown namespace: ' + str(f['namespace']))
        if 'matter_id' in f and f['matter_id'] not in matters:
            raise ValueError('Collected file names an unknown matter: ' + f['path'])
        if 'kind' in f:
            contracts._text(f['kind'], 'A source kind')
        if 'version' in f:
            contracts._text(f['version'], 'A source version', 100)
        if 'sender_roles' in f:
            if not isinstance(f['sender_roles'], dict):
                raise ValueError('sender_roles must map addresses to roles')
            for address, role in f['sender_roles'].items():
                contracts._text(address, 'A sender address', 320)
                identifier(role)
        is_authority = f['namespace'] == 'authority'
        if is_authority != ('authority' in f):
            raise _wrong(f)
        if is_authority:
            if 'matter_id' in f or 'version' in f or 'sender_roles' in f or _extension(f['path']) != '.txt':
                raise _wrong(f)
            authority = f['authority']
            fields(authority, list(AUTHORITY_TYPES) + list(OPTIONAL_AUTHORITY_TYPES), list(AUTHORITY_TYPES))
            for key, kind in {**AUTHORITY_TYPES, **OPTIONAL_AUTHORITY_TYPES}.items():
                if key in authority and not isinstance(authority[key], kind):
                    raise ValueError('Authority ' + key + ' has the wrong JSON type: ' + f['path'])
            version = (authority['authority_id'], authority['version'])
            if version in versions:      # identical bytes would make the second record vanish as a duplicate
                raise ValueError('Duplicate authority version in the collection: ' + version[0] + '@' + version[1])
            versions.add(version)
        else:
            if 'kind' not in f:
                raise ValueError('A collected source needs a kind: ' + f['path'])
            if (f['namespace'] in ('evidence', 'prior_brief')) != ('matter_id' in f):
                raise _wrong(f)
    return collection


def validate_visibility(visibility, collection):
    """{path: (source_set, sorted excluded_matters)}: exactly one rule per collected file, under the namespace rules."""
    fields(visibility, ['schema_version', 'rules'], ['schema_version', 'rules'])
    contracts._version(visibility['schema_version'], 'Unsupported visibility manifest version')
    if not isinstance(visibility['rules'], list):
        raise ValueError('Visibility rules must be a list')
    collected = {f['path']: f for f in collection['files']}
    matters = {m['matter_id']: m for m in collection['matters']}
    rules = {}
    for rule in visibility['rules']:
        fields(rule, ['path', 'source_set', 'excluded_matters'], ['path', 'source_set'])
        path = rule['path']
        if not isinstance(path, str):
            raise ValueError('A visibility rule needs a path')
        if path in rules:
            raise ValueError('Duplicate visibility rule: ' + path)
        if path not in collected:
            raise ValueError('Visibility rule for a file that is not collected: ' + path)
        if rule['source_set'] not in contracts.SOURCE_SETS:
            raise ValueError('Unknown source set: ' + str(rule['source_set']))
        f, source_set = collected[path], rule['source_set']
        excluded = rule.get('excluded_matters', [])
        if not isinstance(excluded, list) or set(excluded) - set(matters) or len(set(excluded)) != len(excluded):
            raise ValueError('excluded_matters must list distinct matters of the collection: ' + path)
        # Grader material belongs in the rubric, never in a collected file; the corpus is a candidate set.
        if source_set == 'grader' or (f['namespace'] == 'authority' and source_set != 'candidate'):
            raise _wrong(f)
        if f['namespace'] == 'prior_brief' and source_set == 'candidate':
            family = matters[f['matter_id']]['family_id']      # a brief reveals the resolution of the paired matter too
            if {m for m, value in matters.items() if value['family_id'] == family} - set(excluded):
                raise _wrong(f)
        rules[path] = (source_set, sorted(excluded))
    for f in collection['files']:
        if f['path'] not in rules:
            raise ValueError('Missing visibility rule: ' + f['path'])
    return rules


def _authority_text(data):
    text = data.decode('utf-8')
    return _normalise(text[1:] if text.startswith('\ufeff') else text)[0].strip()


def _ingest_files(directory, collection, rules, root=None):
    """(run, [(file, its new source records, its report entries)]) for every collected file in collection order."""
    run, placed, owner, total = _Run(root), [], {}, 0
    for f in collection['files']:
        path = contracts._inside(directory, f['path'])
        if not path.is_file():
            raise ValueError('Collected file is missing: ' + f['path'])
        size = path.stat().st_size
        total += size
        if total > LIMITS['max_total_bytes']:
            raise ValueError(f"Collected files exceed {LIMITS['max_total_bytes']} bytes in total")
        first_source, first_entry = len(run.sources), len(run.entries)
        rule = rules[f['path']]
        ext = _extension(f['path'])
        if size > LIMITS['max_file_bytes']:      # not read into memory
            run.entry(f['path'], '', sha256_file(path), size, MEDIA_TYPES.get(ext, 'application/octet-stream'), 'unsupported', ['too_large'])
        else:
            # An authority version is its own source: two versions with byte-identical text are not duplicates.
            slot = f['authority']['authority_id'] + '@' + f['authority']['version'] if 'authority' in f else f.get('matter_id', '')
            run.add(path.read_bytes(), path=f['path'], part='', ext=ext, namespace=f['namespace'], kind=f.get('kind', 'authority'),
                    matter_id=slot, sender_roles=_roles(f.get('sender_roles')), depth=0, parent=None)
        entries = run.entries[first_entry:]
        for e in entries:      # one source, one visibility: a duplicate may not move a record to another set
            if e['status'] == 'duplicate' and owner.get(e['duplicate_of']) != rule:
                raise _wrong(f)
        records = run.sources[first_source:]
        for record in records:
            owner[record['source_id']] = rule
            record['version'] = f.get('version', '1')
        placed.append((f, records, entries))
    return run, placed


def _dump(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _manifests(directory, collection, rules, root=None):
    """({file name: object} of the generated manifests, the ingestion run, its placed files)."""
    run, placed = _ingest_files(directory, collection, rules, root)
    head = {'schema_version': 1, 'data_class': collection['data_class'], 'jurisdiction_profile': collection['jurisdiction_profile']}
    matters = {m['matter_id']: {**m, 'sources': []} for m in collection['matters']}
    shared, authorities, other = [], [], {'oracle': [], 'review': []}
    for f, records, _ in placed:
        source_set, excluded = rules[f['path']]
        if f['namespace'] == 'authority':
            if records:
                text = _authority_text(contracts._inside(directory, f['path']).read_bytes())
                authorities.append({**f['authority'], 'text': text, 'text_sha256': contracts.text_digest(text),
                                    'original_sha256': records[0]['original_sha256']})
            continue
        for record in records:      # attachments inherit the rule of their root file
            stamped = {**record, 'source_set': source_set, 'excluded_matters': list(excluded)}
            record = {key: stamped[key] for key in SOURCE_ORDER if key in stamped}
            if source_set != 'candidate':
                other[source_set].append({**record, 'matter_id': f.get('matter_id')})
            elif f['namespace'] == 'evidence':
                matters[f['matter_id']]['sources'].append(record)
            else:
                shared.append(record)
    out = {'matters.json': {**head, 'source_set': 'candidate', 'matters': [matters[k] for k in sorted(matters)]}}
    if shared:
        out['matters.json']['shared_sources'] = shared
    corpus = {**head, 'source_set': 'candidate', 'venues': collection['venues']}
    corpus.update({key: collection[key] for key in ('policy', 'availability_cutoff') if key in collection})
    corpus['authorities'] = sorted(authorities, key=lambda a: (a['authority_id'], a['version']))
    out['corpus.json'] = corpus
    for name in ('oracle', 'review'):
        if other[name]:
            out[name + '.json'] = {**head, 'source_set': name, 'sources': other[name]}
    return out, run, placed


GENERATED = ('matters.json', 'corpus.json', 'oracle.json', 'review.json')


def _manifest_files(collection_path, visibility_path, output_dir):
    collection_path, visibility_path = Path(collection_path).resolve(), Path(visibility_path).resolve()
    directory = collection_path.parent
    if Path(output_dir).resolve() != directory:
        raise ValueError('The output directory must be the directory that holds the collection manifest')
    if collection_path.name != 'collection.json' or visibility_path != directory / 'visibility.json':
        raise ValueError('The manifests must be collection.json and visibility.json in the output directory')
    return directory, collection_path, visibility_path


def _validated(directory, collection, visibility):
    try:
        validate_collection(collection, directory)
        return validate_visibility(visibility, collection)
    except (TypeError, AttributeError, KeyError):
        raise ValueError('Malformed collection or visibility manifest') from None


def ingest_collection(collection_path, visibility_path, output_dir, root=None):
    """Ingest every collected file and write matters.json, corpus.json, oracle.json and review.json (when a rule assigns those
    sets) and ingest-report.json into `output_dir`, which must hold the collection manifest. Returns the report."""
    directory, collection_path, visibility_path = _manifest_files(collection_path, visibility_path, output_dir)
    collection, _ = contracts.read_json_strict(collection_path)
    if isinstance(collection, dict) and collection.get('data_class') == 'private-matter':
        raise ValueError('Private matter ingestion is not available')
    visibility, _ = contracts.read_json_strict(visibility_path)
    rules = _validated(directory, collection, visibility)
    manifests, run, _ = _manifests(directory, collection, rules, root)
    report = {'schema_version': 1, 'capabilities_sha256': _capabilities(root)[1], 'files': run.entries}
    data = {name: _dump(value) for name, value in manifests.items()}
    for name, payload in data.items():      # a suite that cannot be locked is not produced silently
        if len(payload) > contracts.MAX_SOURCE_BYTES:
            raise ValueError('Generated manifest exceeds the per-file limit: ' + name)
    data['ingest-report.json'] = _dump(report)
    for name in ('oracle.json', 'review.json'):
        if name not in data and (directory / name).exists():
            (directory / name).unlink()
    for name, payload in data.items():
        (directory / name).write_bytes(payload)
    return report


def lock_suite(directory, *, benchmark_id, revision, split_id):
    """Write suite.lock.json for an ingested directory: the manifests, collection, visibility, oracle and review manifests
    when present, and every collected original under purpose `source`. Refuses unparsed files and unverified anchors."""
    directory = Path(directory).resolve()
    if not (directory / 'rubric.json').is_file():
        raise ValueError('Suite needs a rubric.json')
    try:
        report, _ = contracts.read_json_strict(directory / 'ingest-report.json')
        unparsed = [e['path'] + ('#' + e['part'] if e['part'] else '') for e in report['files'] if e['status'] not in ('ok', 'duplicate')]
    except OSError:
        raise ValueError('Suite has no ingest report') from None
    except (TypeError, KeyError, AttributeError):
        raise ValueError('Malformed ingest report') from None
    if unparsed:
        raise ValueError('Suite has unparsed files: ' + ', '.join(unparsed))
    collection, _ = contracts.read_json_strict(directory / 'collection.json')
    try:
        validate_collection(collection, directory)
    except (TypeError, AttributeError, KeyError):
        raise ValueError('Malformed collection manifest') from None
    if collection['data_class'] == 'private-matter':
        raise ValueError('Private matter ingestion is not available')
    manifests = {'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json', 'collection': 'collection.json',
                 'visibility': 'visibility.json'}
    manifests.update({name: name + '.json' for name in ('oracle', 'review') if (directory / (name + '.json')).is_file()})
    lock = contracts.make_lock(directory, benchmark_id=benchmark_id, revision=revision, split_id=split_id, data_class=collection['data_class'],
                               jurisdiction_profile=collection['jurisdiction_profile'], manifests=manifests,
                               sources=[f['path'] for f in collection['files']])
    staged, target = directory / '.suite.lock.json.staged', directory / 'suite.lock.json'
    staged.write_bytes(_dump(lock))
    try:
        problems = verify_anchors(contracts.load_suite(staged))
        if problems:
            raise ValueError('Suite anchors do not verify: ' + '; '.join(problems[:10]))
    except BaseException:
        staged.unlink()
        raise
    os.replace(staged, target)
    return target


def _stored(suite):
    sources = [s for m in suite['matters']['matters'] for s in m['sources']] + list(suite['matters'].get('shared_sources', []))
    for name in ('oracle', 'review'):
        if suite.get(name) is not None:
            sources += suite[name]['sources']
    return sources


def _pinned_root(source, by_id, originals):
    root = contracts._root_source(source, by_id)
    return root is not None and root.get('original_sha256') in originals


def _regenerated(suite):
    """(problems, run, placed): the manifests regenerated in memory from the pinned collection, visibility manifest and
    originals, compared byte for byte with the pinned manifests. Nothing is written or fetched."""
    directory = Path(suite['paths']['collection']).parent
    collection = validate_collection(suite['collection'])
    try:
        generated, run, placed = _manifests(directory, collection, validate_visibility(suite['visibility'], collection))
    except (OSError, ValueError) as error:
        return ['collection: ' + str(error)], None, None
    # The generated manifests follow from the authored collection and the pinned originals alone: anything else in them
    # (a moved or dropped source, an edited date, role, matter or authority record) is a contradiction.
    problems = []
    for name in GENERATED:
        digest = hashlib.sha256(_dump(generated[name])).hexdigest() if name in generated else None
        if digest != suite['file_sha256'].get(name):
            problems.append(name + ': differs from the manifest generated from the collection')
    return problems, run, placed


def _generated_problems(suite):
    """The regeneration check `contracts.load_suite` runs for a suite with a collection manifest."""
    return _regenerated(suite)[0]


def verify_anchors(suite):
    """Sorted problems of the anchored sources of a loaded suite (empty when clean). A collection suite is re-ingested from
    its pinned originals; an imported suite is checked against the text of its pinned copies at each `text` locator."""
    problems, stored = [], _stored(suite)
    originals = suite.get('originals') or {}
    by_id = {s['source_id']: s for s in stored}
    fresh = None
    if suite.get('collection') is not None:
        directory = Path(suite['paths']['collection']).parent
        problems, run, placed = _regenerated(suite)
        if run is None:
            return problems
        fresh = {s['source_id']: s for s in run.sources}
        corpus = {(a['authority_id'], a['version']): a for a in suite['corpus']['authorities']}
        for f, records, _ in placed:
            if f['namespace'] != 'authority' or not records:
                continue
            key = (f['authority']['authority_id'], f['authority']['version'])
            text = _authority_text(contracts._inside(directory, f['path']).read_bytes())
            record = corpus.get(key)
            if record is None or record.get('text_sha256') != contracts.text_digest(text) or record.get('original_sha256') != records[0]['original_sha256']:
                problems.append(f'{key[0]}@{key[1]}: authority text differs from its original')
    for s in stored:
        if 'original_sha256' not in s:
            continue
        sid = s['source_id']
        if not _pinned_root(s, by_id, originals):
            problems.append(sid + ': original file is not pinned')
            continue
        if s.get('parse', {}).get('status') != 'ok':
            problems.append(sid + ': parse status is ' + str(s.get('parse', {}).get('status')))
        if fresh is not None:
            again = fresh.get(sid)
            if again is None or again['original_sha256'] != s['original_sha256']:
                problems.append(sid + ': no such source is extracted from the pinned originals')
                continue
            spans = {span['span_id']: span for span in again['spans']}
            for span in s['spans']:
                other = spans.get(span['span_id'])
                if other is None or other['text_sha256'] != span['text_sha256'] or other.get('locator') != span.get('locator'):
                    problems.append(span['span_id'] + ': span text differs from the original at its locator')
            if set(spans) - {span['span_id'] for span in s['spans']}:
                problems.append(sid + ': the original yields spans the manifest does not hold')
        elif suite.get('dataset') is not None:
            try:
                text = Path(originals[s['original_sha256']]).read_bytes().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
            except (KeyError, OSError, UnicodeDecodeError):
                problems.append(sid + ': original file is not readable as UTF-8 text')
                continue
            for span in s['spans']:
                locator = span.get('locator') or {}
                if locator.get('kind') != 'text' or contracts.text_digest(text[locator['start']:locator['end']]) != span['text_sha256']:
                    problems.append(span['span_id'] + ': span text differs from the original at its locator')
    return sorted(problems)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.ingest',
                                     description='Ingest raw matter files into suite manifests (offline; nothing is fetched or executed).')
    parser.add_argument('--collection', required=True, help='collection.json (operator-authored)')
    parser.add_argument('--visibility', required=True, help='visibility.json beside the collection manifest')
    parser.add_argument('--output', required=True, help='the directory that holds both manifests')
    parser.add_argument('--lock', action='store_true', help='also write suite.lock.json (needs rubric.json)')
    parser.add_argument('--benchmark-id')
    parser.add_argument('--revision')
    parser.add_argument('--split-id')
    args = parser.parse_args(argv)
    try:
        report = ingest_collection(args.collection, args.visibility, args.output)
        summary = {'files': len(report['files']), 'status': {}}
        for entry in report['files']:
            summary['status'][entry['status']] = summary['status'].get(entry['status'], 0) + 1
        if args.lock:
            if not (args.benchmark_id and args.revision and args.split_id):
                raise ValueError('--lock needs --benchmark-id, --revision and --split-id')
            summary['lock'] = str(lock_suite(args.output, benchmark_id=args.benchmark_id, revision=args.revision, split_id=args.split_id))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
