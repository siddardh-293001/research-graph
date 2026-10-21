import streamlit as st
import pandas as pd
import numpy as np
import os
from html import escape
import textwrap

from src.search import SearchEngine
from src.artifacts import resolve_run, latest_tier_s_run

from pyvis.network import Network


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="ResearchGraph",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# HTML RENDERING HELPER
# ============================================================

def render_html(html):
    """Render multiline HTML without Markdown interpreting indentation as code."""
    cleaned = textwrap.dedent(html).strip()
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines())

    st.markdown(
        cleaned,
        unsafe_allow_html=True
    )


# ============================================================
# CUSTOM STYLING
# ============================================================

render_html(
    """
    <style>

    /* ========================================================
       GLOBAL
       ======================================================== */

    .main {
        background: #0b0f19;
    }

    .block-container {
        max-width: 1400px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    /* ========================================================
       HERO
       ======================================================== */

    .hero-title {
        font-size: 3.4rem;
        font-weight: 800;
        letter-spacing: -0.04em;
        line-height: 1.1;
        margin-bottom: 0.35rem;
    }

    .hero-gradient {
        background: linear-gradient(
            90deg,
            #60a5fa,
            #a78bfa
        );
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .hero-subtitle {
        font-size: 1.12rem;
        color: #9ca3af;
        max-width: 850px;
        line-height: 1.6;
        margin-bottom: 1.5rem;
    }

    /* ========================================================
       SEARCH
       ======================================================== */

    .search-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        color: #94a3b8;
        margin-bottom: 0.35rem;
    }

    .search-hint {
        color: #64748b;
        font-size: 0.82rem;
        margin-top: 0.25rem;
        margin-bottom: 1.2rem;
    }

    /* ========================================================
       METRICS
       ======================================================== */

    .metric-card {
        background: linear-gradient(
            145deg,
            #111827,
            #0f172a
        );
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 1.1rem 1.2rem;
        min-height: 105px;
    }

    .metric-label {
        color: #94a3b8;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .metric-value {
        color: #f8fafc;
        font-size: 1.7rem;
        font-weight: 750;
        margin-top: 0.35rem;
    }

    /* ========================================================
       SECTION HEADINGS
       ======================================================== */

    .section-title {
        font-size: 1.45rem;
        font-weight: 700;
        margin-top: 0.5rem;
        margin-bottom: 0.25rem;
    }

    .section-description {
        color: #94a3b8;
        margin-bottom: 1rem;
    }

    /* ========================================================
       INFO CARDS
       ======================================================== */

    .info-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 1.15rem;
        height: 100%;
    }

    .info-card-title {
        font-weight: 700;
        font-size: 1rem;
        margin-bottom: 0.4rem;
    }

    .info-card-text {
        color: #94a3b8;
        line-height: 1.55;
        font-size: 0.9rem;
    }

    /* ========================================================
       CLICKABLE EXAMPLE QUERY CARDS
       ======================================================== */

    .stButton > button {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 14px;
        color: #f8fafc;
        font-size: 0.98rem;
        font-weight: 650;
        text-align: left;
        min-height: 62px;
        padding: 0.9rem 1rem;
        transition: all 0.18s ease;
    }

    .stButton > button:hover {
        border-color: #60a5fa;
        color: #bfdbfe;
        background: #162033;
        transform: translateY(-1px);
    }

    .stButton > button:focus {
        border-color: #60a5fa;
        box-shadow: 0 0 0 1px #60a5fa;
    }

        /* ========================================================
       PAPER RESULT CARDS
       ======================================================== */

    .paper-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.75rem;
    }

    .paper-title {
        font-weight: 650;
        line-height: 1.4;
    }

    .paper-meta {
        color: #94a3b8;
        font-size: 0.82rem;
        margin-top: 0.35rem;
    }

    /* ========================================================
       TOPIC / COMMUNITY CHIPS
       ======================================================== */

    .chip {
        display: inline-block;
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        background: rgba(96, 165, 250, 0.12);
        border: 1px solid rgba(96, 165, 250, 0.25);
        color: #bfdbfe;
        font-size: 0.76rem;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
    }

    /* ========================================================
       SIDEBAR
       ======================================================== */

    section[data-testid="stSidebar"] {
        background: #080c14;
        border-right: 1px solid #1f2937;
    }

    /* ========================================================
       TABS
       ======================================================== */

    button[data-baseweb="tab"] {
        font-size: 0.92rem;
        font-weight: 650;
    }

    /* ========================================================
       DIVIDERS
       ======================================================== */

    hr {
        border-color: #1f2937;
    }

    /* ========================================================
       DATAFRAME
       ======================================================== */

    [data-testid="stDataFrame"] {
        border-radius: 12px;
        overflow: hidden;
    }

    /* ========================================================
       BUTTONS
       ======================================================== */

    .stButton > button {
        border-radius: 9px;
    }

    </style>
    """,
    )


# ============================================================
# DATA LOADING
# ============================================================

@st.cache_resource
def load_search_engine(directory):
    return SearchEngine.from_run(directory)


try:
    run_directory, _ = resolve_run(os.environ.get("RESEARCHGRAPH_RUN_DIR") or latest_tier_s_run())
    engine = load_search_engine(str(run_directory))
except (ValueError, OSError) as error:
    st.error(f"Could not load the research corpus: {error}")
    st.stop()

research_df = engine.papers
embeddings = engine.embeddings
research_graph = engine.graph


def search_papers(query, top_k=10):
    return engine.search(query, mode=retrieval_mode, top_k=top_k,
                         year_min=year_range[0], year_max=year_range[1],
                         topic_ids=selected_topics or None)


# ============================================================
# NETWORK VISUALIZATION
# ============================================================

def create_network(results, max_nodes=45):

    selected_nodes = set(
        results["_graph_node"].astype(int).tolist()
    )

    # --------------------------------------------------------
    # Build a compact query-centric neighborhood
    # --------------------------------------------------------

    expanded_nodes = set(selected_nodes)

    for node in list(selected_nodes):

        if node not in research_graph:
            continue

        neighbors = sorted(research_graph.neighbors(node),
                           key=lambda n: (-research_graph[node][n]["weight"], n))

        # Only a few contextual neighbors per result.
        expanded_nodes.update(neighbors[:4])

    expanded_nodes = sorted(selected_nodes) + sorted(expanded_nodes - selected_nodes)
    expanded_nodes = expanded_nodes[:max(max_nodes, len(selected_nodes))]
    expanded_node_set = set(expanded_nodes)

    network = Network(
        height="650px",
        width="100%",
        bgcolor="#0b0f19",
        font_color="#e5e7eb",
        cdn_resources="in_line",
        directed=False
    )

    # --------------------------------------------------------
    # Network layout
    # --------------------------------------------------------

    network.set_options(
        """
        {
          "nodes": {
            "shape": "dot",
            "borderWidth": 1,
            "font": {
              "size": 11,
              "color": "#e5e7eb"
            }
          },

          "edges": {
            "width": 1,
            "color": {
              "color": "rgba(148,163,184,0.20)",
              "highlight": "#60a5fa"
            },
            "smooth": {
              "enabled": true,
              "type": "continuous"
            }
          },

          "physics": {
            "enabled": true,

            "barnesHut": {
              "gravitationalConstant": -12000,
              "centralGravity": 0.08,
              "springLength": 220,
              "springConstant": 0.025,
              "damping": 0.35,
              "avoidOverlap": 1
            },

            "stabilization": {
              "enabled": true,
              "iterations": 300,
              "fit": true
            }
          },

          "interaction": {
            "hover": true,
            "dragNodes": true,
            "zoomView": true,
            "navigationButtons": true,
            "hideEdgesOnDrag": true,
            "tooltipDelay": 150
          }
        }
        """
    )

    # --------------------------------------------------------
    # Add nodes
    # --------------------------------------------------------

    for node in expanded_nodes:

        if node < 0 or node >= len(research_df):
            continue

        row = research_df.iloc[int(node)]

        title = escape(str(row["title"]))
        topic = escape(str(row["topic_name"]))
        community = row["community"]

        matching_result = results[
            results["_graph_node"] == node
        ]

        is_result = not matching_result.empty

        if is_result:

            similarity = float(
                matching_result.iloc[0]["score"]
            )

            size = 24 + 20 / (1 + int(matching_result.index[0]))

            label = (
                title[:24] + "..."
                if len(title) > 27
                else title
            )

            # Plain text prevents PyVis from displaying raw
            # HTML tags in the tooltip.
            tooltip = (
                f"{title}\n"
                f"Year: {row['year']}\n"
                f"Topic: {topic}\n"
                f"Community: {community}\n"
                f"Citations: {row['citation_count']}\n"
                f"Retrieval score: {similarity:.4f}"
            )

            border_width = 3

        else:

            size = 9

            # Context nodes have no visible labels.
            label = ""

            tooltip = (
                f"{title}\n"
                f"Year: {row['year']}\n"
                f"Topic: {topic}\n"
                f"Community: {community}\n"
                f"Citations: {row['citation_count']}"
            )

            border_width = 1

        network.add_node(
            int(node),
            label=label,
            title=tooltip,
            size=size,
            borderWidth=border_width
        )

    # --------------------------------------------------------
    # Add only query-centric edges
    #
    # We keep:
    #   selected ↔ selected
    #   selected ↔ context
    #
    # We intentionally remove:
    #   context ↔ context
    #
    # This prevents the visualization from becoming a
    # dense "hairball".
    # --------------------------------------------------------

    for source, target in research_graph.edges():

        if (
            source not in expanded_node_set
            or target not in expanded_node_set
        ):
            continue

        source_selected = source in selected_nodes
        target_selected = target in selected_nodes

        if source_selected or target_selected:

            network.add_edge(
                int(source),
                int(target)
            )

    return network


# ============================================================
# HEADER
# ============================================================

render_html(
    """
    <div class="hero-title">
        🔬 Research<span class="hero-gradient">Graph</span>
    </div>

    <div class="hero-subtitle">
        Explore the research landscape through semantic search,
        NLP topic modeling, and research-network analysis.
    </div>
    """,
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("## 🔬 ResearchGraph")

    st.caption(
        "NLP-Driven Research Landscape Analysis"
    )

    st.divider()

    st.markdown("### Search Settings")

    top_k = st.slider(
        "Retrieved papers",
        min_value=5,
        max_value=20,
        value=10,
        step=1
    )

    retrieval_mode = st.selectbox("Ranking method", ["hybrid", "bm25", "dense"])
    year_range = st.slider("Publication years", int(research_df.year.min()),
                           int(research_df.year.max()),
                           (int(research_df.year.min()), int(research_df.year.max())))
    topic_names = research_df.set_index("topic_id").topic_name.to_dict()
    selected_topics = st.multiselect("Topics (empty means all)", sorted(topic_names),
                                     format_func=lambda i: topic_names[i])

    st.divider()

    st.markdown("### Corpus")
    st.caption("Tier S · OpenAlex snapshot" if engine.manifest.get("kind") == "tier_s" else "Recovered baseline corpus")

    col_a, col_b = st.columns(2)

    with col_a:
        st.metric(
            "Papers",
            f"{len(research_df):,}"
        )

    with col_b:
        st.metric(
            "Topics",
            research_df["topic_name"].nunique()
        )

    st.metric(
        "Communities",
        research_df["community"].nunique()
    )

    st.divider()

    st.markdown("### Model")

    st.caption(
        "Sentence Transformer"
    )

    st.caption(
        "`all-MiniLM-L6-v2`"
    )

    st.caption(
        f"Embeddings: {embeddings.shape[1]} dimensions"
    )

    st.divider()

    st.markdown("### Network")

    st.caption(
        f"Nodes: {research_graph.number_of_nodes():,}"
    )

    st.caption(
        f"Edges: {research_graph.number_of_edges():,}"
    )


# ============================================================
# SEARCH STATE
# ============================================================

if "query_input" not in st.session_state:
    st.session_state.query_input = ""


def set_search_query(query_text):
    st.session_state.query_input = query_text


render_html('<div class="search-label">RESEARCH QUERY</div>')
query = st.text_input("Research query", key="query_input",
                      placeholder="Ask about a research topic...", label_visibility="collapsed",
                      max_chars=engine.config['max_query_chars'])

render_html(
    """
    <div class="search-hint">
        Try: graph-based RAG · multimodal RAG ·
        LLM hallucination · agentic retrieval
    </div>
    """,
    )


# ============================================================
# SEARCH RESULTS
# ============================================================

if query.strip():

    with st.spinner(
        "Exploring the research landscape..."
    ):

        results = search_papers(
            query,
            top_k=top_k
        )

    if results.empty:
        st.info("No papers match this query and these filters. Try broader terms or filters.")
        st.stop()

    # ========================================================
    # QUERY SUMMARY
    # ========================================================

    mean_similarity = results["score"].mean()
    median_similarity = results["score"].median()

    community_counts = (
        results["community"]
        .value_counts()
    )

    dominant_community = community_counts.index[0]
    dominant_community_count = community_counts.iloc[0]

    topic_counts = (
        results["topic_name"]
        .value_counts()
    )

    dominant_topic = topic_counts.index[0]

    render_html(
        '<div class="section-title">Research Landscape</div>',
    )

    render_html(
        f'<div class="section-description">'
        f'Results for <b>{escape(query)}</b>'
        f'</div>',
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Mean Retrieval Score",
            f"{mean_similarity:.3f}"
        )

    with col2:
        st.metric(
            "Median Retrieval Score",
            f"{median_similarity:.3f}"
        )

    with col3:
        st.metric(
            "Top Community",
            str(dominant_community)
        )

    with col4:
        st.metric(
            "Top Topic",
            dominant_topic
        )

    st.caption(
        f"{dominant_community_count} of the "
        f"{len(results)} retrieved papers belong to "
        f"community {dominant_community}."
    )

    st.divider()

    # ========================================================
    # TABS
    # ========================================================

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📄 Papers",
            "🧠 Topics",
            "🕸️ Communities",
            "🌐 Research Network"
        ]
    )


    # ========================================================
    # PAPERS TAB
    # ========================================================

    with tab1:

        render_html(
            '<div class="section-title">'
            'Related Papers'
            '</div>',
    )

        st.caption(
            {"hybrid": "Ranked by reciprocal rank fusion of BM25 and semantic search.",
             "bm25": "Ranked by BM25 term matching over titles and abstracts.",
             "dense": "Ranked by cosine similarity of query and paper embeddings."}[retrieval_mode]
        )

        # ----------------------------------------------------
        # Search result cards
        # ----------------------------------------------------

        for rank, (_, row) in enumerate(
            results.iterrows(),
            start=1
        ):

            render_html(
                f"""
                <div class="paper-card">
                    <div class="paper-title">
                        {rank}. {escape(str(row["title"]))}
                    </div>

                    <div class="paper-meta">
                        {row["year"]}
                        &nbsp;•&nbsp;
                        {row["citation_count"]:,} citations
                        &nbsp;•&nbsp;
                        retrieval score {row["score"]:.4f}
                    </div>

                    <div style="margin-top:0.45rem;">
                        <span class="chip">
                            {escape(str(row["topic_name"]))}
                        </span>

                        <span class="chip">
                            Community {row["community"]}
                        </span>
                    </div>
                </div>
                """,
    )

            if row["shared_terms"]:
                st.caption("Shared terms: " + ", ".join(row["shared_terms"]))
            if row["matching_sentence"]:
                st.write(row["matching_sentence"])
            st.caption(f"BM25 rank: {row['bm25_rank']} · Dense rank: {row['dense_rank']}")

        # ----------------------------------------------------
        # Detailed table
        # ----------------------------------------------------

        with st.expander("View results as a table"):

            display_df = results[
                [
                    "title",
                    "year",
                    "citation_count",
                    "relative_citations",
                    "topic_name",
                    "community",
                    "score"
                ]
            ].copy()

            display_df["score"] = (
                display_df["score"]
                .round(4)
            )

            display_df["relative_citations"] = (
                display_df["relative_citations"]
                .round(2)
            )

            display_df = display_df.rename(
                columns={
                    "title": "Paper",
                    "year": "Year",
                    "citation_count": "Citations",
                    "relative_citations": "Relative Citations",
                    "topic_name": "NLP Topic",
                    "community": "Community",
                    "score": "Retrieval Score"
                }
            )

            st.dataframe(
                display_df,
                width="stretch",
                hide_index=True
            )

        # ----------------------------------------------------
        # Paper details
        # ----------------------------------------------------

        render_html(
            '<div class="section-title">'
            'Paper Details'
            '</div>',
    )

        selected_paper = st.selectbox(
            "Select a paper",
            results["paper_id"].tolist(),
            format_func=lambda paper_id: results.set_index("paper_id").loc[paper_id, "title"]
        )

        selected_row = results[
            results["paper_id"] == selected_paper
        ].iloc[0]

        col1, col2 = st.columns(2)

        with col1:

            render_html(
                f"### {escape(str(selected_row['title']))}"
            )

            st.write(
                f"**Year:** {selected_row['year']}"
            )

            st.write(
                f"**Citations:** "
                f"{selected_row['citation_count']:,}"
            )

            st.write(
                f"**Relative citations:** "
                f"{selected_row['relative_citations']:.2f}"
            )

        with col2:

            st.write(
                f"**NLP topic:** "
                f"{selected_row['topic_name']}"
            )

            st.write(
                f"**Network community:** "
                f"{selected_row['community']}"
            )

            st.write(
                f"**Retrieval score:** "
                f"{selected_row['score']:.4f}"
            )

            st.write(
                f"**PageRank:** "
                f"{selected_row['pagerank']:.6f}"
            )


    # ========================================================
    # TOPICS TAB
    # ========================================================

    with tab2:

        st.markdown(
            '<div class="section-title">'
            'NLP Topic Distribution'
            '</div>',
    )

        st.caption(
            "Distribution of retrieved papers across the "
            "NMF-derived NLP topics."
        )

        topic_display = (
            topic_counts
            .rename("paper_count")
            .to_frame()
        )

        topic_display["percentage"] = (
            topic_display["paper_count"]
            / len(results)
            * 100
        ).round(1)

        st.bar_chart(
            topic_display["paper_count"]
        )

        st.dataframe(
            topic_display.rename(
                columns={
                    "paper_count": "Papers",
                    "percentage": "Share (%)"
                }
            ),
            width="stretch"
        )

        render_html(
            '<div class="section-title">'
            'Topic Interpretation'
            '</div>',
    )

        topic_descriptions = {
            "Core RAG & Retrieval":
                "Retrieval-Augmented Generation and retrieval systems.",

            "Computational Linguistics":
                "Computational linguistics and language technologies.",

            "Surveys & Research Directions":
                "Survey papers, reviews, challenges and future research directions.",

            "Agentic RAG & Multi-Agent Systems":
                "Agentic AI, multi-agent systems and agentic RAG.",

            "Multimodal RAG":
                "Multimodal retrieval, vision-language systems and multimodal RAG.",

            "NLP / Computational Linguistics":
                "Natural language processing and computational linguistics.",

            "Medical & Clinical LLMs":
                "Healthcare, clinical and medical applications of language models.",

            "Graph RAG & Knowledge Graphs":
                "Knowledge graphs, graph-based retrieval and Graph RAG.",

            "LLM Training & Fine-Tuning":
                "Model training, fine-tuning, adaptation and performance.",

            "Question Answering & Retrieval":
                "Question answering, multi-hop QA and retrieval-based answering."
        }

        for topic in topic_counts.index:

            description = topic_descriptions.get(
                topic,
                ""
            )

            percentage = (
                topic_counts[topic]
                / len(results)
                * 100
            )

            render_html(
                f"""
                <div class="info-card" style="margin-bottom:0.7rem;">
                    <div class="info-card-title">
                        {topic}
                    </div>

                    <div class="info-card-text">
                        {description}
                        <br><br>
                        <b>{int(topic_counts[topic])}</b>
                        retrieved papers
                        &nbsp;•&nbsp;
                        <b>{percentage:.1f}%</b> of results
                    </div>
                </div>
                """,
    )


    # ========================================================
    # COMMUNITIES TAB
    # ========================================================

    with tab3:

        render_html(
            '<div class="section-title">'
            'Research Network Communities'
            '</div>',
    )

        st.caption(
            "Communities were detected from the paper "
            "similarity network using network structure."
        )

        community_display = (
            community_counts
            .rename("paper_count")
            .to_frame()
        )

        community_display["percentage"] = (
            community_display["paper_count"]
            / len(results)
            * 100
        ).round(1)

        st.bar_chart(
            community_display["paper_count"]
        )

        st.dataframe(
            community_display.rename(
                columns={
                    "paper_count": "Papers",
                    "percentage": "Share (%)"
                }
            ),
            width="stretch"
        )

        render_html(
            '<div class="section-title">'
            'Community Composition'
            '</div>',
    )

        for community in community_counts.index:

            community_papers = results[
                results["community"] == community
            ]

            topics_in_community = (
                community_papers["topic_name"]
                .value_counts()
            )

            dominant = (
                topics_in_community.index[0]
                if not topics_in_community.empty
                else "Unknown"
            )

            share = (
                len(community_papers)
                / len(results)
                * 100
            )

            render_html(
                f"""
                <div class="info-card" style="margin-bottom:0.7rem;">
                    <div class="info-card-title">
                        Community {community}
                    </div>

                    <div class="info-card-text">
                        <b>{len(community_papers)}</b>
                        retrieved papers
                        &nbsp;•&nbsp;
                        <b>{share:.1f}%</b> of results
                        <br><br>
                        Dominant NLP topic:
                        <b>{dominant}</b>
                    </div>
                </div>
                """,
    )


    # ========================================================
    # NETWORK TAB
    # ========================================================

    with tab4:

        render_html(
            '<div class="section-title">'
            'Research Similarity Network'
            '</div>',
    )

        st.caption(
            "Highlighted nodes are papers returned by your query. "
            "Smaller nodes provide local network context. "
            "Hover over a node for paper metadata."
        )

        # ----------------------------------------------------
        # Network summary
        # ----------------------------------------------------

        network_col1, network_col2, network_col3 = st.columns(3)

        with network_col1:

            st.metric(
                "Retrieved Papers",
                len(results)
            )

        with network_col2:

            st.metric(
                "Visible Nodes",
                min(
                    45,
                    len(results) + len(results) * 4
                )
            )

        with network_col3:

            st.metric(
                "Corpus Edges",
                f"{research_graph.number_of_edges():,}"
            )

        st.markdown("")

        # ----------------------------------------------------
        # Legend
        # ----------------------------------------------------

        render_html(
            """
            <div style="
                background:#111827;
                border:1px solid #1f2937;
                border-radius:10px;
                padding:0.75rem 1rem;
                margin-bottom:0.8rem;
                color:#94a3b8;
                font-size:0.84rem;
            ">
                <b style="color:#f8fafc;">Network legend:</b>
                &nbsp;
                Larger labelled nodes = retrieved papers
                &nbsp;•&nbsp;
                Small nodes = local context
                &nbsp;•&nbsp;
                Edges = semantic similarity relationships
            </div>
            """,
    )

        network = create_network(
            results,
            max_nodes=45
        )

        network_html = network.generate_html()

        st.iframe(network_html, height=670)

        render_html(
            '<div class="section-title">'
            'How to read the network'
            '</div>',
    )

        st.write(
            """
            Each node represents a research paper. The underlying
            graph connects papers based on semantic similarity.

            The visualization is intentionally query-centric:
            retrieved papers are emphasized and only a limited number
            of nearby papers are shown as context. This keeps the
            network interpretable instead of displaying the entire
            dense research graph at once.
            """
        )


# ============================================================
# LANDING PAGE
# ============================================================

else:

    st.info(
        "Enter a research question above to explore "
        "the ResearchGraph corpus."
    )

    render_html(
        '<div class="section-title">'
        'Explore the research landscape'
        '</div>',
    )

    st.caption(
        "ResearchGraph connects semantic search, NLP topics, "
        "citation-aware analysis and network communities."
    )

    # --------------------------------------------------------
    # Example queries
    # --------------------------------------------------------

    example_queries = [
        "graph based retrieval augmented generation",
        "knowledge graph enhanced RAG",
        "multimodal retrieval augmented generation",
        "LLM hallucination mitigation",
        "agentic retrieval systems",
        "medical applications of large language models",
        "fine tuning large language models",
        "question answering with retrieval"
    ]

    query_cols = st.columns(2)

    for i, example in enumerate(example_queries):

        with query_cols[i % 2]:

            clicked = st.button(
                f"🔎 {example}",
                key=f"example_query_{i}",
                width="stretch",
                on_click=set_search_query,
                args=(example,)
            )

            st.caption(
                "Search the corpus for semantically related "
                "papers and inspect their topics and network structure."
            )

    st.divider()

    # --------------------------------------------------------
    # What ResearchGraph does
    # --------------------------------------------------------

    render_html(
        '<div class="section-title">'
        'What ResearchGraph does'
        '</div>',
    )

    feature_cols = st.columns(4)

    features = [
        (
            "🔎",
            "Hybrid Search",
            "Combines keyword and semantic retrieval with year and topic filters."
        ),
        (
            "🧠",
            "NLP Topic Modeling",
            "Uses NMF-based topic modeling to identify research themes."
        ),
        (
            "🕸️",
            "Network Analysis",
            "Represents papers as nodes in a semantic similarity network and detects communities."
        ),
        (
            "📊",
            "Integrated Analysis",
            "Connects semantic search, NLP topics, citations and network structure."
        )
    ]

    for col, (icon, title, description) in zip(
        feature_cols,
        features
    ):

        with col:

            render_html(
                f"""
                <div class="info-card">
                    <div style="font-size:1.5rem;">
                        {icon}
                    </div>

                    <div class="info-card-title">
                        {title}
                    </div>

                    <div class="info-card-text">
                        {description}
                    </div>
                </div>
                """,
    )

    st.divider()

    # --------------------------------------------------------
    # Corpus overview
    # --------------------------------------------------------

    render_html(
        '<div class="section-title">'
        'Corpus Overview'
        '</div>',
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Research Papers",
            f"{len(research_df):,}"
        )

    with col2:

        st.metric(
            "NLP Topics",
            research_df["topic_name"].nunique()
        )

    with col3:

        st.metric(
            "Network Communities",
            research_df["community"].nunique()
        )

    with col4:

        st.metric(
            "Network Edges",
            f"{research_graph.number_of_edges():,}"
        )

    st.caption(
        "Embedding model: all-MiniLM-L6-v2 · "
        f"Embedding dimension: {embeddings.shape[1]}"
    )
