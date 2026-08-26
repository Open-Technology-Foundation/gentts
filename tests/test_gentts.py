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


if __name__ == '__main__':
  unittest.main()

#fin
