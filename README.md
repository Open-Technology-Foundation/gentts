# gentts — Markdown to speech

**Location:** `/ai/scripts/Audio/gentts/`
**Version:** 1.0.0
**Status:** Active

Generates MP3 audio from Markdown files. Strips everything unspeakable, converts document
structure into pause markers, renders those markers for the chosen TTS provider, synthesises in
chunks and concatenates the result.

Generalised from `garydean.id`'s `tts/generate_tts.py`, which read essays from a SQLite `essays`
table. Here the per-file settings come from YAML frontmatter instead, so the tool works on any
Markdown tree — a book, a docs directory, a single essay.

---

## Quick Start

```bash
gentts essay.md                      # -> essay.mp3
gentts --preview essay.md            # show processed text + first chunk, no API call
gentts -l chapters/                  # list files and audio status
gentts -O audio/ chapters/           # batch a directory into audio/
gentts --stamp -O audio/ chapters/   # ... and record file/duration in each frontmatter
gentts -p openai essay.md            # different provider
gentts -F essay.md                   # regenerate over an existing MP3
```

Nothing is regenerated if the output already exists — `-F` forces it.

---

## Frontmatter

Every key is optional. Document-level keys are the ordinary ones; audio settings live under an
`audio:` mapping so the block drops into existing site or book frontmatter without colliding.

```yaml
---
title: In Search of Dharma
subtitle: A natural history of ethics
author: Biksu Okusi
date: 2026-08-01
language: en
audio:
  title: "0: In Search of Dharma"  # spoken title, if not the document title
  subtitle: Preface                # likewise subtitle, author, date
  strip_h1: true                # drop a leading H1 the preamble already says
  provider: google              # google | openai | grok | compatible
  voice: en-AU-Chirp3-HD-Charon # overrides the gender/language voice table
  gender: male                  # male | female
  lang_code: en-AU
  output: ../html/audio/dharma.mp3
  lexicon: ./book_lexicon.json  # or false to disable substitution
  speaking_rate: 0.95
  preamble: true                # speak title/subtitle/author/date first
  skip: false                   # exclude from batch runs
  timestamp: false              # give the MP3 this file's mtime
  markers: punctuation          # punctuation | tags (non-SSML providers)
  url: ...                      # 'compatible' provider only
  model: ...
  key_env: ...
  chunk_limit: ...
---
```

Precedence is **CLI flag > `audio:` frontmatter > built-in default**.

`title`, `subtitle`, `author` and `date` are spoken as a preamble before the body; set
`preamble: false` to suppress it. `date` accepts `YYYY-MM-DD`, `YYYY-MM`, `YYYY` or a YAML date,
and is spoken as "August 2026".

Each of those four may be overridden under `audio:`, for documents whose spoken identity differs
from their document identity — a book part titled `Preface` that a website publishes as
`0: In Search of Dharma`, with `Preface` as its subtitle. Where a document repeats its title as a
leading `# H1`, `strip_h1: true` drops it so the preamble does not say it twice.

### Written back by `--stamp`

`--stamp` rewrites the frontmatter with where the audio landed:

```yaml
audio:
  file: out/tiny.mp3
  duration: 10
  duration_hms: '0:10'
```

`-T`/`--timestamp` (or `audio.timestamp: true`) gives the MP3 the Markdown file's mtime, so a later
`ls -lt` or `find -newer` shows at a glance which MP3s are in sync with their source: equal mtimes
mean current, a newer `.md` means the audio is stale. The copy runs **after** `--stamp`'s
frontmatter rewrite, so the equality holds even when both flags are used together.

`-l` applies the same comparison: an MP3 older than its `.md` is listed as `stale` instead of a
duration, and the summary line counts the stale files.

`audio.file` is metadata (read by `-l`), distinct from `audio.output`, which is configuration.
Note that `--stamp` re-serialises the frontmatter through PyYAML, so comments and exotic
formatting in that block are not preserved.

---

## Output location

Resolved in this order:

1. `-o FILE` — single input only
2. `audio.output` in frontmatter — relative to the Markdown file
3. `-O DIR` — batch output directory, file named after the Markdown stem
4. sibling `<stem>.mp3`

A **bare filename** in `audio.output` names the file but not the directory, so `-O` still supplies
the directory. That lets a repository declare its published audio filename without committing
anyone's deployment path:

```yaml
audio:
  output: 0-in-search-of-dharma.mp3   # not 0-preface.mp3
```

```bash
gentts book/            # -> book/0-in-search-of-dharma.mp3
gentts -O html/audio book/    # -> html/audio/0-in-search-of-dharma.mp3
```

---

## What gets stripped

Markdown is prose-first, so the pipeline is conservative — it removes only what is clearly not
speech.

| Removed entirely | Kept, markup dropped |
|------------------|----------------------|
| Fenced code blocks (``` and ~~~) | Headings → pause markers |
| Markdown pipe tables (2+ consecutive `\|` lines) | Blockquotes → prosody span |
| HTML `table`, `pre`, `style`, `script`, `audio`, `video`, `figure`, `iframe` | Bullet and ordered-list markers |
| `<image>`, `<vidframe>`, `<IKLAN>`, music-player sections | Bold, italic, links, wiki-links |
| Footnote references and definitions | `figcaption` text |
| HTML comments, stage directions (`[Cut to...]`) | Horizontal rules → long pause |

Indented (4-space) blocks are **not** treated as code: in prose that indentation is far more often
a quotation or a verse.

### Excluding a region

Fence it in the body. An unclosed `stop` excludes everything to the end of the file — useful for
a long references or notes section.

```markdown
<!--audio stop-->
Bibliography, notes, anything that should not be read aloud.
<!--audio restart-->
```

---

## Pause markers

Preprocessing produces an intermediate form carrying markers, which each provider renders in its
own way. This is why one pipeline feeds three different APIs.

| Marker | Google (SSML) | OpenAI-style | Grok-style |
|--------|---------------|--------------|------------|
| `[PAUSE_SHORT]` | `<break time="400ms"/>` | `... ` | `[pause]` |
| `[PAUSE_MEDIUM]` | `<break time="800ms"/>` | newline | `[pause]` |
| `[PAUSE_LONG]` | `<break time="1200ms"/>` | blank line | `[long-pause]` |
| `[PAUSE_XLONG]` | `<break time="2000ms"/>` | `...` | `[long-pause] [long-pause]` |
| `[QUOTE_START/END]` | `<prosody rate="95%" pitch="-1st">` | newline | `[pause]` |

Paragraph breaks become 1000 ms, single newlines 200 ms, sentence ends 330 ms — so a paragraph
boundary carries ~1.5 s in total (sentence + paragraph + newline breaks combine).

---

## Providers

### `google` (default)

Google Cloud TTS over REST, authenticated with Application Default Credentials. Chirp3-HD voices
require principal-asserting credentials — plain API keys are rejected.

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT
```

The only provider supporting SSML, and therefore the only one that gets true break timing,
blockquote prosody and lexicon pronunciation. Default voices:

| Language | Male | Female |
|----------|------|--------|
| `en` | `en-AU-Chirp3-HD-Charon` | `en-AU-Chirp3-HD-Aoede` |
| `id` | `id-ID-Chirp3-HD-Puck` | `id-ID-Chirp3-HD-Autonoe` |

Any other language needs an explicit `voice` and `lang_code`.

Requests retry with exponential backoff (2s doubling to 30s, five attempts) on 429/500/502/503/504
— Chirp3-HD returns quota errors under sustained load, and a book-length run is dozens of
sequential calls.

### `openai`, `grok`, `compatible`

One OpenAI-shaped `/audio/speech` backend with three presets. `compatible` takes its values from
frontmatter or flags, so any service using the same request shape works.

| Provider | Endpoint | Model | Voice | Key | Chunk limit |
|----------|----------|-------|-------|-----|-------------|
| `openai` | `api.openai.com` | `tts-1-hd` | `onyx` | `OPENAI_API_KEY` | 4000 |
| `grok` | `api.x.ai` | `grok-tts` | `tara` | `XAI_API_KEY` | 14000 |
| `compatible` | *required* | *required* | *required* | *required* | 4000 |

```bash
gentts -p compatible --url https://tts.local/v1/audio/speech \
       --model my-tts --voice narrator --key-env MY_TTS_KEY essay.md
```

---

## Pronunciation lexicon

`tts_lexicon.json` maps terms to pronunciations for the Google provider. Two value forms:

```json
{
  "musyawarah": "muʃaˈwarah",
  "dhṛ": {"say": "dree"}
}
```

A string is IPA, emitted as `<phoneme alphabet="ipa">`. A `{"say": ...}` object is a plain
respelling, emitted as `<sub alias>`. The respelling form exists because Chirp 3 HD's text
normaliser spells all-consonant clusters out as initialisms and **overrides `<phoneme>` but not
`<sub>`**. Substituted aliases also get a leading 50 ms break, or Chirp glues the alias onto the
preceding word ("root dhṛ" → "rootdree").

Lookup order:

1. `--lexicon FILE`
2. `audio.lexicon` in frontmatter (`false` disables)
3. `tts_lexicon.json` beside the Markdown file
4. the bundled `tts_lexicon.json` — **English content only**, since its entries respell foreign
   terms for an English voice

---

## Chunking

Providers cap request size, so long documents are split and the parts concatenated with 0.5 s of
silence between them.

Google chunks on **bytes** of SSML (3500, under the 5000 limit — break tags are most of the
overhead), splitting at `<break>` tags, then sentences. `<prosody>` spans crossing a chunk
boundary are closed and reopened so no chunk ships unbalanced markup.

The other providers chunk on characters, at paragraph boundaries, then sentences, then hard-wrap —
a single sentence longer than the limit would otherwise be rejected outright.

---

## Options

```
  -l, --list              list files and audio status, generate nothing
  -r, --recursive         recurse into directory arguments
      --preview           show processed text and first chunk, no API call
  -F, --force             regenerate even if the output exists
      --stamp             write audio.file/duration back into the frontmatter
  -T, --timestamp         set the output MP3's mtime to the input file's mtime
  -p, --provider P        google | openai | grok | compatible
  -g, --gender G          male | female
  -v, --voice NAME        explicit voice name
      --lang-code CODE    e.g. en-AU
      --language LANG     content language key, e.g. en or id
      --speaking-rate N   default 0.95
      --lexicon FILE      pronunciation lexicon JSON
      --url URL           endpoint (compatible provider)
  -m, --model NAME        model (compatible provider)
      --key-env VAR       environment variable holding the API key
      --chunk-limit N     max characters per request (non-google)
      --markers M         punctuation | tags
  -o, --output FILE       output MP3 (single input only)
  -O, --outdir DIR        output directory for batch runs
  -q, --quiet             suppress progress output
  -V, --version
  -h, --help
```

---

## Dependencies

| Requirement | Used for |
|-------------|----------|
| Python 3.12+ | the script itself |
| PyYAML | frontmatter (`apt install python3-yaml`) |
| `ffmpeg`, `ffprobe` | chunk concatenation, duration reporting |
| `gcloud` | ADC access token, Google provider only |

No virtualenv. Stdlib plus PyYAML, HTTP over `urllib`.

## Install on PATH

```bash
symlink -S /ai/scripts/Audio
```

## Licence

GPL-3.0 — see [LICENSE](LICENSE).

## Exit codes

| Code | Meaning |
|------|---------|
| 1 | provider or ffmpeg failure |
| 3 | file not found (input, lexicon, credentials) |
| 4 | malformed frontmatter or lexicon |
| 18 | missing required command |
| 19 | missing API key or GCP quota project |
| 22 | invalid option or incomplete provider configuration |
| 130 | interrupted |

#fin
