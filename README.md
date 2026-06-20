# musicman

**Organise your music library by tag-based rules.**

musicman is a terminal-based tool that reads existing metadata from your
music files, matches them against user-defined rules, and organises them
into a structured directory tree — move, copy, or symlink, with a dry-run
mode to preview before committing.

## Quick start

```bash
pip install musicman

# Generate a sample config to get started
musicman init

# Preview what would happen (no files changed)
musicman organise ~/Downloads/songs/ --dry-run

# Run for real
musicman organise ~/Downloads/songs/
```

## How it works

1. **Scan** — musicman walks your source directories and finds audio files
   (MP3, FLAC, M4A, Ogg, WAV, WMA, and more).
2. **Read** — it reads existing metadata tags using
   [mutagen](https://github.com/quodlibet/mutagen). No external APIs, no
   network calls.
3. **Match** — rules are evaluated in order. The first rule whose
   conditions match wins.
4. **Organise** — files are moved, copied, or symlinked into the output
   directory using your template pattern.

## Config

Configuration lives in a JSON file. musicman looks for
`musicman-rules.json` in the current directory, then
`~/.config/musicman/rules.json`.

```json
{
  "rules": [
    {
      "name": "Jazz from 1950s",
      "conditions": {
        "all": [
          { "tag": "genre", "op": "contains", "value": "jazz" },
          { "tag": "date", "op": "gte", "value": 1950 },
          { "tag": "date", "op": "lt", "value": 1960 }
        ]
      },
      "output": "Jazz/1950s/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Classical pre-1800",
      "conditions": {
        "all": [
          { "tag": "genre", "op": "matches", "value": "(?i)classical" },
          { "tag": "date", "op": "lt", "value": 1800 }
        ]
      },
      "output": "Classical/Pre-1800/{artist}/{album}/{track:02d} - {title}{ext}"
    }
  ],
  "defaults": {
    "output": "Unsorted/{artist} - {title}{ext}",
    "action": "move"
  },
  "settings": {
    "output_base_dir": "~/Music/Organized",
    "overwrite": "skip",
    "delete_empty_sources": false
  }
}
```

### Conditions reference

| Operator | Meaning | Example |
|---|---|---|
| `eq` / `neq` | String equality (case-insensitive) | `"genre" "eq" "Jazz"` |
| `contains` | Substring match | `"genre" "contains" "rock"` |
| `matches` | Regex match | `"genre" "matches" "(?i)classical"` |
| `gt` / `gte` / `lt` / `lte` | Numeric comparison | `"date" "gte" 2000` |
| `in` | Value in list | `"genre" "in" ["Rock", "Metal"]` |
| `exists` / `not_exists` | Tag presence | `"composer" "exists" true` |

Conditions can be nested with `all` (AND) and `any` (OR) combinators.

### Template placeholders

| Placeholder | Source |
|---|---|
| `{title}` | Track title |
| `{artist}` | Track artist |
| `{album}` | Album name |
| `{albumartist}` | Album artist (e.g. "Various Artists") |
| `{genre}` | Genre tag |
| `{year}` / `{date}` | Year / date |
| `{track}` | Track number |
| `{track_total}` | Total tracks |
| `{disc}` / `{disc_total}` | Disc number |
| `{composer}` | Composer |
| `{ext}` | File extension (e.g. `.mp3`) |

Format specs work: `{track:02d}` → `01`, `{track:03d}` → `001`.

Missing tags become `"Unknown"`. Slashes in tag values are sanitised to
prevent path injection.

## CLI reference

```
Usage: musicman [OPTIONS] COMMAND [ARGS]...

Commands:
  organise  Categorise and organise music files according to rules.
  init      Generate a sample musicman-rules.json config file.
  validate  Validate a rules JSON config file.
  tags      Display all metadata tags from a single audio file.
```

### organise

```
musicman organise [SOURCES]... [OPTIONS]

Options:
  -c, --config PATH   Path to rules JSON file.
  -n, --dry-run       Preview only — no files are changed.
  -o, --output DIR    Override output base directory.
  -v, --verbose       Show matched tags per file.
  --quiet             Suppress per-file output; show summary only.
```

### Examples

```bash
# Preview what a new config would do
musicman organise ~/Music/Inbox/ -c my-rules.json -n

# Organise with a custom output directory
musicman organise ~/Downloads/songs/ -o ~/Music/Sorted/

# Check what tags a file has
musicman tags song.flac -v

# Validate your rules
musicman validate musicman-rules.json

# Quiet mode — just the numbers
musicman organise ~/Music/Inbox/ --quiet
```

## Supported formats

MP3, FLAC, M4A, AAC, Ogg Vorbis, Opus, WAV, WMA.

## Development

```bash
git clone https://github.com/YOUR_USER/musicman
cd musicman
pip install -e ".[dev]"
pytest
```

## License

MIT
