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


if __name__ == '__main__':
  unittest.main()

#fin
