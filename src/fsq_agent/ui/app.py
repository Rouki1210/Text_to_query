"""Streamlit chat interface (Sprint 2).

Run:  streamlit run src/fsq_agent/ui/app.py
"""

import plotly.express as px
import streamlit as st

from fsq_agent.core.agent import Agent

st.set_page_config(page_title="Feature Store Analyst", page_icon="📊", layout="wide")
st.title("📊 Feature Store Analyst")
st.caption("Ask questions about real estate and EV data in plain English.")


@st.cache_resource
def get_agent() -> Agent:
    return Agent()


if "history" not in st.session_state:
    st.session_state.history = []

for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("e.g. Compare EV revenue and listing prices by region last month"):
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            result = get_agent().answer(question)

        # Always show the SQL for auditability.
        with st.expander("Generated SQL", expanded=False):
            st.code(result.sql, language="sql")

        if result.error:
            st.error(f"Query failed after {result.attempts} attempts: {result.error}")
            st.session_state.history.append(
                {"role": "assistant", "content": f"Query failed: {result.error}"}
            )
        else:
            df = result.dataframe
            st.dataframe(df, use_container_width=True)

            # Say so when the guard held something back, rather than showing a
            # silently narrower table than the question asked for.
            if withheld := df.attrs.get("withheld_columns"):
                st.warning(
                    f"{len(withheld)} column(s) withheld — these hold credentials "
                    f"or personal data and are never returned: {', '.join(withheld)}"
                )

            # Naive auto-chart: one categorical + one numeric column -> bar chart.
            numeric = df.select_dtypes("number").columns
            categorical = df.select_dtypes(exclude="number").columns
            if len(numeric) >= 1 and len(categorical) >= 1 and len(df) <= 50:
                st.plotly_chart(
                    px.bar(df, x=categorical[0], y=numeric[0]),
                    use_container_width=True,
                )
            st.session_state.history.append(
                {"role": "assistant", "content": f"Returned {len(df)} rows."}
            )
