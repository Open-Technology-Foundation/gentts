#!/usr/bin/env python3
"""Regression tests for gentts. Stdlib only, no network, no provider calls.

Run:  python3 -m unittest discover -s tests -v
"""

import argparse
import os
import runpy
import tempfile
import time
import unittest
from pathlib import Path

G = runpy.run_path(str(Path(__file__).resolve().parent.parent / 'gentts'))


def cli(**kw):
  """Namespace of every CLI flag resolve_settings reads, all None unless given."""
  fields = ('language', 'provider', 'speaking_rate', 'gender', 'voice', 'lang_code',
            'url', 'model', 'key_env', 'chunk_limit', 'markers', 'lexicon')
  return argparse.Namespace(**{f: kw.get(f) for f in fields})


class StampPreservesMtime(unittest.TestCase):
  """2.1: rewriting frontmatter must not make the .md newer than its MP3."""

  def test_write_frontmatter_keeps_source_mtime(self):
    with tempfile.TemporaryDirectory() as d:
      md = Path(d) / 'a.md'
      md.write_text('---\ntitle: T\n---\nHello.\n')
      old = time.time() - 100
      os.utime(md, (old, old))
      meta, body = G['read_markdown'](md)
      meta['audio']['file'] = 'a.mp3'
      G['write_frontmatter'](md, meta, body)
      self.assertAlmostEqual(md.stat().st_mtime, old, places=3)
      self.assertIn('file: a.mp3', md.read_text())


class ClauseBreaksKeepNewlines(unittest.TestCase):
  """2.2: add_clause_breaks must never consume paragraph or line breaks."""

  def test_paragraph_break_after_colon_survives(self):
    text = 'Consider the following:\n\n' + ', '.join(f'item number {i} is here' for i in range(20))
    out = G['add_clause_breaks'](text)
    self.assertIn('Consider the following:\n\n', out)

  def test_verse_lines_survive(self):
    lines = [f'line {i} of the poem goes on and on and on,' for i in range(8)]
    out = G['add_clause_breaks']('\n'.join(lines))
    self.assertEqual(out.count('\n'), 7)


class LiteralAngleBrackets(unittest.TestCase):
  """2.4: a < in prose is not a tag."""

  def test_comparison_in_prose_kept(self):
    out = G['preprocess_content']('If a < b and c > d then fine.')
    self.assertEqual(out, 'If a < b and c > d then fine.')

  def test_real_tags_still_stripped(self):
    self.assertEqual(G['preprocess_content']('<b>bold</b> and <br/> x'), 'bold and x')


class FrontmatterTrust(unittest.TestCase):
  """2.3/2.6: frontmatter cannot redirect an env secret to an arbitrary host."""

  def test_preset_provider_rejects_frontmatter_url(self):
    meta = {'audio': {'provider': 'openai', 'url': 'http://127.0.0.1:1/x', 'key_env': 'HOME'}}
    with self.assertRaises(SystemExit) as cm:
      G['resolve_settings'](Path('x.md'), meta, cli())
    self.assertEqual(cm.exception.code, 22)

  def test_compatible_frontmatter_url_must_be_https(self):
    meta = {'audio': {'provider': 'compatible', 'url': 'http://tts.local/v1/audio/speech',
                      'model': 'm', 'voice': 'v', 'key_env': 'K'}}
    with self.assertRaises(SystemExit) as cm:
      G['resolve_settings'](Path('x.md'), meta, cli())
    self.assertEqual(cm.exception.code, 22)

  def test_compatible_frontmatter_https_accepted(self):
    meta = {'audio': {'provider': 'compatible', 'url': 'https://tts.local/v1/audio/speech',
                      'model': 'm', 'voice': 'v', 'key_env': 'K'}}
    cfg = G['resolve_settings'](Path('x.md'), meta, cli())
    self.assertEqual(cfg['url'], 'https://tts.local/v1/audio/speech')

  def test_cli_url_may_be_http(self):
    meta = {'audio': {'provider': 'compatible', 'model': 'm', 'voice': 'v', 'key_env': 'K'}}
    cfg = G['resolve_settings'](Path('x.md'), meta, cli(url='http://localhost:8080/v1/audio/speech'))
    self.assertTrue(cfg['url'].startswith('http://localhost'))


class RealWorldChapter(unittest.TestCase):
  """tests/example-text.md: a real book chapter run through the whole pipeline."""

  @classmethod
  def setUpClass(cls):
    cls.md = Path(__file__).resolve().parent / 'example-text.md'
    cls.meta, cls.body = G['read_markdown'](cls.md)
    body = G['strip_leading_h1'](cls.body)
    cls.text = G['preprocess_content'](G['build_preamble'](cls.meta) + body)

  def test_preamble_uses_spoken_identity_and_h1_is_not_repeated(self):
    self.assertTrue(self.text.startswith('In Search of Dharma.\n\n8: Creating Dharmas.'))
    self.assertEqual(self.text.count('8: Creating Dharmas'), 1)

  def test_unclosed_audio_stop_excludes_rest_of_file(self):
    self.assertIn('The thing we were always doing', self.text)
    self.assertNotIn('Sources', self.text)
    self.assertNotIn('arXiv', self.text)

  def test_no_markup_residue(self):
    for residue in ('**', '](', '<image', '<!--', '[^', '\n#', '* '):
      self.assertNotIn(residue, self.text, residue)

  def test_epigraph_blockquote_becomes_quote_span(self):
    self.assertRegex(self.text, r'\[QUOTE_START\]\s*We have always created our dharmas')
    self.assertEqual(self.text.count('[QUOTE_START]'), self.text.count('[QUOTE_END]'))

  def test_ssml_chunks_within_limit_and_balanced(self):
    chunks = G['chunk_ssml'](G['text_to_ssml'](G['add_clause_breaks'](self.text), {}))
    self.assertGreater(len(chunks), 1)
    for c in chunks:
      self.assertLessEqual(len(c.encode('utf-8')), G['GOOGLE_CHUNK_LIMIT'])
      self.assertEqual(c.count('<prosody'), c.count('</prosody>'))
      self.assertNotIn('[PAUSE', c)
      self.assertNotIn('[QUOTE', c)

  def test_plain_text_has_no_markers(self):
    self.assertNotRegex(G['text_to_plain'](self.text), r'\[(PAUSE|QUOTE)_')

  def test_bare_output_filename_combines_with_outdir(self):
    args = argparse.Namespace(output=None, outdir='/audio')
    self.assertEqual(G['resolve_output'](self.md, self.meta, args),
                     Path('/audio/8-in-search-of-dharma.mp3'))

  def test_preview_runs_clean(self):
    import subprocess
    r = subprocess.run([str(self.md.parent.parent / 'gentts'), '--preview', str(self.md)],
                       capture_output=True, text=True)
    self.assertEqual(r.returncode, 0, r.stderr)
    self.assertEqual(r.stderr, '')
    self.assertIn('Total chunks:', r.stdout)


class SetextHeadings(unittest.TestCase):
  """2.13: a --- underline after text is an H2, not a horizontal rule."""

  def test_setext_h2_becomes_heading(self):
    out = G['preprocess_content']('Intro.\n\nChapter Two\n---\n\nBody.')
    self.assertIn('[PAUSE_MEDIUM]Chapter Two[PAUSE_SHORT]', out)
    self.assertNotIn('[PAUSE_XLONG]', out)

  def test_real_hr_still_long_pause(self):
    self.assertIn('[PAUSE_XLONG]', G['preprocess_content']('One.\n\n---\n\nTwo.'))


class FootnoteReferences(unittest.TestCase):
  """2.8: only footnote-shaped brackets are deleted."""

  def test_bracketed_prose_with_digits_kept(self):
    out = G['preprocess_content']('Under [Law 22/1999] the region [circa 1850] was split.')
    self.assertEqual(out, 'Under [Law 22/1999] the region [circa 1850] was split.')

  def test_footnote_refs_removed(self):
    self.assertEqual(G['preprocess_content']('Word[^1] and word[12] and[^note].'),
                     'Word and word and.')


class OrderedListMarkers(unittest.TestCase):
  """2.9: a sentence-initial year is not a list marker."""

  def test_year_kept(self):
    out = G['preprocess_content']('It ended in\n1999. That was the year.')
    self.assertIn('1999. That was the year.', out)

  def test_list_marker_stripped(self):
    self.assertEqual(G['preprocess_content']('1. first\n2. second'), 'first\nsecond')


class OutputCollisions(unittest.TestCase):
  """2.7: two inputs resolving to one MP3 is an error before any billing."""

  def test_same_stem_in_two_dirs_detected(self):
    with tempfile.TemporaryDirectory() as d:
      a = Path(d) / 'p1' / 'ch1.md'
      b = Path(d) / 'p2' / 'ch1.md'
      for f in (a, b):
        f.parent.mkdir()
        f.write_text('x')
      args = argparse.Namespace(output=None, outdir=d)
      dupes = G['find_output_collisions']([a, b], args)
      self.assertEqual(len(dupes), 1)
      self.assertEqual(sorted(dupes[0][1]), sorted([a, b]))

  def test_distinct_stems_clean(self):
    with tempfile.TemporaryDirectory() as d:
      a = Path(d) / 'a.md'
      b = Path(d) / 'b.md'
      a.write_text('x')
      b.write_text('x')
      args = argparse.Namespace(output=None, outdir=None)
      self.assertEqual(G['find_output_collisions']([a, b], args), [])


class OutputValidation(unittest.TestCase):
  """2.5/2.11: a bad response never becomes a "current" MP3."""

  def test_json_body_is_not_mp3(self):
    self.assertFalse(G['looks_like_mp3'](b'{"error":{"message":"model not loaded"}}'))

  def test_id3_and_sync_frames_are_mp3(self):
    self.assertTrue(G['looks_like_mp3'](b'ID3\x04\x00' + b'\x00' * 10))
    self.assertTrue(G['looks_like_mp3'](b'\xff\xfb\x90\x00' + b'\x00' * 10))

  def test_empty_output_is_not_current(self):
    with tempfile.TemporaryDirectory() as d:
      md = Path(d) / 'a.md'
      mp3 = Path(d) / 'a.mp3'
      md.write_text('x')
      time.sleep(0.01)
      mp3.write_bytes(b'')
      self.assertFalse(G['output_is_current'](md, mp3))
      mp3.write_bytes(b'\xff\xfb' + b'\x00' * 100)
      self.assertTrue(G['output_is_current'](md, mp3))

  def test_finalize_rejects_empty_and_keeps_existing(self):
    with tempfile.TemporaryDirectory() as d:
      good = Path(d) / 'out.mp3'
      good.write_bytes(b'GOOD')
      part = Path(d) / 'part.mp3'
      part.write_bytes(b'')
      with self.assertRaises(G['TTSError']):
        G['finalize_output'](part, good)
      self.assertEqual(good.read_bytes(), b'GOOD')


class LexiconSubstitution(unittest.TestCase):
  """2.10: emitted tags are never rescanned for shorter terms."""

  def test_nested_terms_produce_well_formed_xml(self):
    from xml.dom import minidom
    out = G['apply_lexicon_ssml']('Pak Harto spoke.', {'Pak Harto': 'pak harto', 'Harto': 'harto'})
    minidom.parseString(f'<speak>{out}</speak>')
    self.assertEqual(out.count('<phoneme'), 1)

  def test_term_matching_attribute_text_does_not_corrupt_it(self):
    from xml.dom import minidom
    out = G['apply_lexicon_ssml']('karma and ipa.', {'karma': 'kɑːmə', 'ipa': 'aɪpiːeɪ'})
    minidom.parseString(f'<speak>{out}</speak>')
    self.assertIn('alphabet="ipa"', out)


class SsmlChunkLimits(unittest.TestCase):
  """2.12: no chunk over the byte limit, no silence-only chunk."""

  def test_punctuation_free_run_is_hard_wrapped(self):
    text = G['add_clause_breaks']('Intro.\n\n' + ('word ' * 1000).strip() + '\n\nOutro.')
    chunks = G['chunk_ssml'](G['text_to_ssml'](text, {}))
    for c in chunks:
      self.assertLessEqual(len(c.encode('utf-8')), G['GOOGLE_CHUNK_LIMIT'])
    self.assertEqual(''.join(chunks).count('word'), 1000)

  def test_no_break_only_chunk(self):
    chunks = G['chunk_ssml'](G['text_to_ssml']('word ' * 900, {}))
    import re
    for c in chunks:
      self.assertTrue(re.sub(r'<[^>]+>', '', c).strip(), c)


class FootnoteDefinitions(unittest.TestCase):
  """2.14: whole multi-paragraph footnote bodies are dropped."""

  def test_indented_continuation_paragraphs_dropped(self):
    src = ('Text[^1].\n\n[^1]: First para.\n    indented cont.\n\n    para after blank.\n\n'
           '[^note]: named.\nlazy continuation\n\nNormal.')
    self.assertEqual(G['preprocess_content'](src), 'Text.\n\nNormal.')


class ReferenceLinks(unittest.TestCase):
  """2.15: [text][ref] speaks the text; [ref]: url lines are dropped."""

  def test_reference_links_and_definitions(self):
    src = 'See [text][1] and [ref].\n\n[1]: http://example.com\n[ref]: http://y "Title"'
    self.assertEqual(G['preprocess_content'](src), 'See text and ref.')


class FrontmatterValueErrors(unittest.TestCase):
  """2.21-2.24: bad frontmatter values exit with the documented codes, not tracebacks."""

  def test_non_numeric_speaking_rate_exits_22(self):
    with self.assertRaises(SystemExit) as cm:
      G['resolve_settings'](Path('x.md'), {'audio': {'speaking_rate': 'fast'}}, cli())
    self.assertEqual(cm.exception.code, 22)

  def test_non_numeric_chunk_limit_exits_22(self):
    meta = {'audio': {'provider': 'openai', 'chunk_limit': '4k'}}
    with self.assertRaises(SystemExit) as cm:
      G['resolve_settings'](Path('x.md'), meta, cli())
    self.assertEqual(cm.exception.code, 22)

  def test_empty_voice_falls_back_to_table(self):
    cfg = G['resolve_settings'](Path('x.md'), {'audio': {'voice': ''}}, cli())
    self.assertEqual(cfg['voice'], 'en-AU-Chirp3-HD-Charon')

  def test_date_false_and_blank_are_silent(self):
    self.assertEqual(G['format_date'](False), '')
    self.assertEqual(G['format_date']('  '), '')
    self.assertEqual(G['format_date']('2026-08'), 'August 2026')

  def test_non_object_lexicon_exits_4(self):
    with tempfile.TemporaryDirectory() as d:
      lex = Path(d) / 'lex.json'
      lex.write_text('["x"]')
      with self.assertRaises(SystemExit) as cm:
        G['load_lexicon'](lex)
      self.assertEqual(cm.exception.code, 4)


class FilesystemErrors(unittest.TestCase):
  """2.25: unreadable input is a documented exit, not a traceback."""

  def test_undecodable_input_exits_4(self):
    with tempfile.TemporaryDirectory() as d:
      md = Path(d) / 'b.md'
      md.write_bytes(b'\xff\xfe bad\n')
      with self.assertRaises(SystemExit) as cm:
        G['read_markdown'](md)
      self.assertEqual(cm.exception.code, 4)

  def test_unreadable_input_exits_3(self):
    if os.geteuid() == 0:
      self.skipTest('root ignores file modes')
    with tempfile.TemporaryDirectory() as d:
      md = Path(d) / 'c.md'
      md.write_text('x')
      md.chmod(0)
      try:
        with self.assertRaises(SystemExit) as cm:
          G['read_markdown'](md)
        self.assertEqual(cm.exception.code, 3)
      finally:
        md.chmod(0o600)


class HttpRetry(unittest.TestCase):
  """2.26: a body truncated mid-read is retried like any other transient failure."""

  def test_incomplete_read_is_retried(self):
    import http.client
    import urllib.request
    calls = []

    class Resp:
      def __enter__(self):
        return self

      def __exit__(self, *a):
        return False

      def read(self):
        calls.append(1)
        if len(calls) == 1:
          raise http.client.IncompleteRead(b'part')
        return b'ok'

    real_open, real_sleep = urllib.request.urlopen, G['time'].sleep
    urllib.request.urlopen = lambda *a, **k: Resp()
    G['time'].sleep = lambda s: None
    try:
      out = G['post_json']('https://x/', b'{}', {}, retries=2)
    finally:
      urllib.request.urlopen, G['time'].sleep = real_open, real_sleep
    self.assertEqual(out, b'ok')
    self.assertEqual(len(calls), 2)


class Blockquotes(unittest.TestCase):
  """2.17: nested markers are stripped; lazy continuation stays in the quote."""

  def test_nested_markers_removed(self):
    out = G['preprocess_content']('> quote line\n> > nested\n> >> deeper\n\nafter')
    self.assertNotIn('>', out)
    self.assertIn('[QUOTE_START]\nquote line\nnested\ndeeper\n[QUOTE_END]', out)

  def test_lazy_continuation_stays_quoted(self):
    out = G['preprocess_content']('> quote\nlazy line\n\nafter')
    self.assertIn('[QUOTE_START]\nquote\nlazy line\n[QUOTE_END]\n\nafter', out)


class Abbreviations(unittest.TestCase):
  """2.18: Dr., Mr., e.g. are not sentence ends."""

  def test_no_ssml_break_after_abbreviation(self):
    out = G['text_to_ssml']('Dr. Smith paid 3.5 dollars, e.g. yes. Mr. Jones', None)
    for abbr in ('Dr.', 'e.g.', 'Mr.'):
      self.assertNotIn(f'{abbr}<break', out, abbr)
    self.assertIn('yes.<break time="330ms"/>', out)

  def test_chunking_keeps_title_with_name(self):
    chunks = G['split_on_sentences']('Mr. Smith went home. ' * 3, 30)
    self.assertEqual(len(chunks), 3)
    for c in chunks:
      self.assertTrue(c.startswith('Mr. Smith'), c)


class NestedEmphasis(unittest.TestCase):
  """2.19: no literal ** survives nested emphasis."""

  def test_bold_containing_italic(self):
    self.assertEqual(G['preprocess_content']('This is **bold *italic* bold** done.'),
                     'This is bold italic bold done.')

  def test_pairing_does_not_bleed_into_later_bold(self):
    self.assertEqual(G['preprocess_content']('**bold *ital* bold** and **plain**'),
                     'bold ital bold and plain')


class FrontmatterOutputPath(unittest.TestCase):
  """2.31: frontmatter audio.output is a repository path, not a shell path."""

  def test_tilde_in_frontmatter_output_is_literal(self):
    meta = {'audio': {'output': '~/x.mp3'}}
    args = argparse.Namespace(output=None, outdir=None)
    out = G['resolve_output'](Path('/repo/a.md'), meta, args)
    self.assertEqual(out, Path('/repo/~/x.mp3'))


class GcloudTimeout(unittest.TestCase):
  """A hung gcloud (e.g. blackholed IPv6) must fail loudly, not block forever."""

  def test_hung_gcloud_exits_with_message(self):
    with tempfile.TemporaryDirectory() as d:
      fake = Path(d) / 'gcloud'
      fake.write_text('#!/bin/sh\nsleep 30\n')
      fake.chmod(0o755)
      adc = Path(d) / 'adc.json'
      adc.write_text('{"quota_project_id": "p"}')
      old_path, old_adc = os.environ['PATH'], G['GOOGLE_ADC_FILE']
      os.environ['PATH'] = f'{d}:{old_path}'
      G['GOOGLE_ADC_FILE'] = adc
      try:
        with self.assertRaises(SystemExit) as cm:
          G['google_credentials'](timeout=1)
      finally:
        os.environ['PATH'], G['GOOGLE_ADC_FILE'] = old_path, old_adc
      self.assertEqual(cm.exception.code, 1)


if __name__ == '__main__':
  unittest.main()

#fin
