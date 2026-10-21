# Fixed retrieval seed benchmark

`queries.json` contains 50 information needs and 77 graded judgments. Query IDs
and texts are fixed for comparisons across corpus tiers. Its version is
`0.1-provisional`; it is a known-paper and topic discovery seed set rather than
a representative, exhaustively judged literature search benchmark.

The assistant selected papers from the supplied corpus, inspected titles and
available abstract metadata, wrote query paraphrases, and assigned grades before
running the retrieval benchmark. Some abstract fields contain only bibliographic
text. Titles therefore support some labels more strongly than abstracts. Every
judgment records its assessor, rationale, title, metadata excerpt and pending
independent review. These are not human-reviewed gold labels.

Grades are 0 (not relevant), 1 (partial background), 2 (relevant) and 3 (directly
relevant). Grades greater than zero count as relevant for MRR and Recall@20.
The negative examples distinguish retrieval-augmented generation from Rag GTPase
biology; the set has limited coverage and is biased toward selected known papers.
The original corpus hash identifies the metadata used to seed the benchmark;
evaluations also record the exact pipeline run and benchmark content hash.

Each evaluation exports `review_pool.csv`, the union of the three systems' top
10 results. It includes query, paper ID, title, metadata excerpt, rank per system,
existing grade, and empty fields for reviewed grade, reviewer and notes. Unjudged
papers stay blank; they are never automatically labelled nonrelevant.

For independent review, assess the pooled results against each information need,
fill the review fields, reconcile disagreements and explicitly revise the
judgments in a new benchmark version while retaining query IDs and texts.
Keep the current benchmark for comparison. Record assessor provenance and
evaluate the new version separately. Do not tune retrieval parameters against
this seed set and then present its scores as held-out performance.
