# Research workspace expansion

The free research workspace adds field browsing (title, abstract, author name,
DOI), 20-record pages, newest/citation/title sorting, saved searches bound to the
release hash and all matching IDs up to the 25,000-paper serving cap, local
collections/notes/tags/status, research trails, JSON/CSV export and validated
JSON restoration preserving existing records.

Paper tools include an expandable 12-node reference/citing/semantic map with
center history, corpus citation chronology, anonymous on-demand OpenAlex
annual counts/open-access links/author identifiers, and an abstract evidence
lookup. Comparison includes a two-paper literature matrix with source sentences.
User-supplied text documents up to 2 MB can be searched for supporting passages
entirely in the browser. No paid model or server-side document upload is used.

Limits are part of the interface:
- Corpus timelines count citing papers by publication year, not global counts.
- OpenAlex access links and author IDs are source-reported; remote availability
  and identity accuracy are not independently guaranteed. Local author search
  matches names and may combine distinct people.
- Full-text support is plain-text passage retrieval, not PDF parsing or generated
  Q&A. Matrix categories are keyword-based excerpts requiring researcher review.
- Topic evolution includes a selectable publication-year chart. Cross-topic
  citation density is normalized by possible paper pairs; it remains a coverage-
  dependent exploration measure, not proof of a research gap.
- Backups restore paper identities; opening papers refreshes live metadata.
  Reading lists and notes remain device-local. No cloud account or sync.
- New-match badges compare observed identities across releases, not publication
  dates or email alerts. The free serving corpus remains capped at 25,000.

Verification includes scripts/check_exploration.py in src.verify, literal-query
and pagination tests, browser navigation regressions, and manual automated
feature scenarios for saved searches, graph navigation, local document passage
retrieval and invalid-backup rejection. Author profiles now include paginated exact-name matches, coauthor counts and
theme counts. Verified identity reconciliation across the frozen corpus,
editable evidence classification and full-text generated Q&A remain unimplemented;
this release must not be described as complete coverage of all advanced ideas.
