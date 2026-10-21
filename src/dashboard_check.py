"""Exercise the real Streamlit application with the pinned local embedding model."""
import json
import os
from streamlit.testing.v1 import AppTest
from src.pipeline import ROOT
from src.artifacts import load_run, latest_tier_s_run


def widget(elements, label):
    return next(e for e in elements if e.label == label)


def check_dashboard():
    _, _, papers, _, _ = load_run(os.environ.get('RESEARCHGRAPH_RUN_DIR') or latest_tier_s_run())
    checks = []
    app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=90).run()

    def clean(name):
        if app.exception:
            raise AssertionError(f'{name}: {[e.message for e in app.exception]}')
        checks.append(name)

    clean('initial_page')
    app.button(key='example_query_0').click().run()
    clean('example_query_updates_search')
    assert app.text_input[0].value == 'graph based retrieval augmented generation'
    assert len(app.dataframe) == 3
    for mode in ['bm25', 'dense', 'hybrid']:
        widget(app.selectbox, 'Ranking method').select(mode).run()
        clean(f'{mode}_search_and_graph_render')
        table = app.dataframe[0].value
        assert 0 < len(table) <= 10
        assert table['Retrieval Score'].is_monotonic_decreasing
    selected_topic = int(papers.topic_id.iloc[0])
    widget(app.multiselect, 'Topics (empty means all)').set_value([selected_topic]).run()
    clean('topic_filter')
    assert app.dataframe[0].value['NLP Topic'].eq(papers.topic_name.iloc[0]).all()
    widget(app.multiselect, 'Topics (empty means all)').set_value([]).run()
    year = int(papers.year.max())
    widget(app.slider, 'Publication years').set_value((year, year)).run()
    clean('year_filter')
    assert app.dataframe[0].value.Year.eq(year).all()
    widget(app.selectbox, 'Ranking method').select('bm25').run()
    app.text_input[0].input('zzzzunfindabletokenzzzz').run()
    clean('empty_results')
    assert any('No papers match' in i.value for i in app.info)
    app.text_input[0].input('').run()
    clean('clear_query_returns_home')
    assert len(app.button) == 8
    return {'passed': True, 'checks': checks}


if __name__ == '__main__':
    print(json.dumps(check_dashboard(), indent=2))
