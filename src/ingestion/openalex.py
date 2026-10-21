import time
import requests
import pandas as pd
from src.corpus import deduplicate_papers, arxiv_from_work


BASE_URL = "https://api.openalex.org/works"

SEARCH_QUERIES = [
    "retrieval augmented generation",
    "retrieval-augmented generation",
    "RAG large language models",
    "retrieval augmented language models",
    "graph RAG",
    "agentic RAG",
    "multimodal RAG",
]


def reconstruct_abstract(inverted_index):
    """Convert OpenAlex's inverted abstract index into normal text."""

    if not inverted_index:
        return None

    words = []

    for word, positions in inverted_index.items():
        for position in positions:
            words.append((position, word))

    words.sort(key=lambda x: x[0])

    return " ".join(word for _, word in words)


def search_openalex(query, pages=2, per_page=100):
    """Search OpenAlex and return raw paper records."""

    results = []

    for page in range(1, pages + 1):

        params = {
            "search": query,
            "filter": "from_publication_date:2020-01-01",
            "per-page": per_page,
            "page": page,
        }

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        results.extend(data["results"])

        print(
            f"  Page {page}: "
            f"{len(data['results'])} papers"
        )

        # Be polite to the API
        time.sleep(0.2)

    return results


def normalize_paper(paper):
    """Convert an OpenAlex record into our simplified schema."""

    authors = []

    for authorship in (paper.get("authorships") or []):

        author = authorship.get("author")

        if author:
            authors.append({
                "id": author.get("id"),
                "name": author.get("display_name"),
            })

    institutions = []

    for authorship in (paper.get("authorships") or []):

        for institution in (authorship.get("institutions") or []):

            institutions.append({
                "id": institution.get("id"),
                "name": institution.get("display_name"),
                "country": institution.get(
                    "country_code"
                ),
            })

    topics = []

    for topic in (paper.get("topics") or []):

        topics.append({
            "id": topic.get("id"),
            "name": topic.get("display_name"),
            "score": topic.get("score"),
        })

    keywords = []

    for keyword in (paper.get("keywords") or []):

        keywords.append({
            "id": keyword.get("id"),
            "name": keyword.get("display_name"),
            "score": keyword.get("score"),
        })

    open_access = paper.get("open_access") or {}

    return {
        "paper_id": paper.get("id"),
        "doi": paper.get("doi"),
        "title": paper.get("title") or paper.get("display_name"),
        "abstract": reconstruct_abstract(
            paper.get("abstract_inverted_index")
        ),
        "year": paper.get("publication_year"),
        "publication_date": paper.get(
            "publication_date"
        ),
        "citation_count": paper.get(
            "cited_by_count", 0
        ),
        "authors": authors,
        "institutions": institutions,
        "topics": topics,
        "keywords": keywords,
        "referenced_works": paper.get("referenced_works") or [],
        "related_works": paper.get("related_works") or [],
        "arxiv_id": arxiv_from_work(paper),
        "updated_date": paper.get("updated_date"),
        "created_date": paper.get("created_date"),
        "is_retracted": bool(paper.get("is_retracted")),
        "language": paper.get("language"),
        "is_open_access": open_access.get(
            "is_oa"
        ),
        "pdf_url": open_access.get(
            "oa_url"
        ),
    }


def main():

    print("=" * 60)
    print("ResearchGraph — OpenAlex Data Ingestion")
    print("=" * 60)

    all_papers = []

    for query in SEARCH_QUERIES:

        print(f"\nSearching: {query}")

        papers = search_openalex(
            query=query,
            pages=2,
            per_page=100,
        )

        all_papers.extend(papers)

    print("\n" + "=" * 60)
    print(
        f"Raw papers collected: {len(all_papers)}"
    )

    normalized = [
        normalize_paper(paper)
        for paper in all_papers
    ]

    before = len(normalized)
    df = pd.DataFrame(deduplicate_papers(normalized))

    after = len(df)

    print(f"Duplicates removed: {before - after}")
    print(f"Unique papers: {after}")

    # Create output directory if necessary
    import os

    os.makedirs(
        "data/processed",
        exist_ok=True
    )

    output_path = (
        "data/processed/papers.parquet"
    )

    df.to_parquet(
        output_path,
        index=False
    )

    print(f"\nSaved to: {output_path}")

    print("\nDataset shape:")
    print(df.shape)

    print("\nYears:")
    print(
        df["year"]
        .value_counts()
        .sort_index()
    )

    print("\nTop papers by citations:")

    print(
        df[
            [
                "title",
                "year",
                "citation_count"
            ]
        ]
        .sort_values(
            "citation_count",
            ascending=False
        )
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
