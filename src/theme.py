import streamlit as st


ARCHIE_THEME_CSS = """
<style>
:root {
    --archie-navy: #17324d;
    --archie-blue: #2f6f9f;
    --archie-blue-soft: #e8f2fb;
    --archie-green: #1f8a5b;
    --archie-green-soft: #e8f6ef;
    --archie-amber: #d9911b;
    --archie-border: #c9dceb;
}

/* Page title and main accents */
h1, h2, h3 {
    color: var(--archie-navy);
}

/* Links */
a {
    color: var(--archie-blue) !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f5f9fc 0%, #eef6fb 100%);
    border-right: 1px solid var(--archie-border);
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: var(--archie-navy);
}

/* Info boxes: Archie blue */
[data-testid="stAlert"] {
    border-radius: 0.75rem;
    border: 1px solid var(--archie-border);
}

[data-testid="stAlert"] div[role="alert"] {
    color: var(--archie-navy);
}

/* Buttons */
.stButton > button {
    border-radius: 999px;
    border: 1px solid var(--archie-blue);
    color: var(--archie-navy);
}

.stButton > button:hover {
    border-color: var(--archie-navy);
    color: var(--archie-navy);
}

/* Tabs */
button[data-baseweb="tab"] {
    color: var(--archie-navy);
}

button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--archie-blue);
    border-bottom-color: var(--archie-blue);
}

/* Inputs */
[data-testid="stChatInput"] textarea,
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div {
    border-radius: 0.65rem;
}

/* Expanders and document cards */
.streamlit-expanderHeader {
    color: var(--archie-navy);
    font-weight: 600;
}

/* Code blocks in instructions tab */
[data-testid="stCodeBlock"] {
    border-radius: 0.75rem;
    border: 1px solid var(--archie-border);
}
</style>
"""


def apply_archie_theme() -> None:
    st.markdown(ARCHIE_THEME_CSS, unsafe_allow_html=True)
