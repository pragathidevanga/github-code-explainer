"""Visual styles for the dark, developer-focused Streamlit interface."""

APP_CSS = """
<style>
:root { --ink:#edf2ff; --muted:#9eabc8; --panel:#111a2d; --line:rgba(148,163,184,.16); --violet:#8b7cff; --cyan:#57d4e5; }
.stApp { background: radial-gradient(ellipse at 50% -15%, rgba(93,75,190,.30), transparent 48%), #080d19; color:var(--ink); font-family:'Segoe UI',Arial,sans-serif; }
.block-container { max-width:1240px; padding-top:2.2rem; padding-bottom:4rem; }
h1,h2,h3 { font-family:'Segoe UI',Arial,sans-serif !important; color:#f4f6ff !important; letter-spacing:-.025em; }
p,li,label,.stMarkdown { color:#d3daeb; }
.hero { padding:2.5rem 2rem 2.2rem; border:1px solid rgba(139,124,255,.25); border-radius:24px; background:linear-gradient(135deg,rgba(25,34,61,.97),rgba(24,20,51,.91)); box-shadow:0 24px 70px rgba(0,0,0,.28); margin:0 0 1.5rem; }
.hero h1 { font-size:clamp(2rem,4vw,3.5rem); line-height:1.05; margin:.75rem 0; }
.hero p { max-width:760px; color:#b8c3dc; font-size:1.05rem; margin:.4rem 0 0; }
.eyebrow { font-size:.76rem; font-weight:700; letter-spacing:.15em; color:#b4aaff; }
.badge { display:inline-flex; align-items:center; gap:.45rem; padding:.35rem .72rem; border-radius:99px; border:1px solid rgba(87,212,229,.25); color:#a5eff4; background:rgba(87,212,229,.08); font-size:.72rem; font-weight:700; letter-spacing:.07em; }
.panel { padding:1.25rem 1.35rem; border-radius:18px; border:1px solid var(--line); background:linear-gradient(145deg,rgba(20,30,49,.96),rgba(15,22,38,.97)); box-shadow:0 12px 32px rgba(0,0,0,.14); margin:.4rem 0 1rem; }
.metric { padding:1rem 1.05rem; min-height:112px; border-radius:16px; border:1px solid var(--line); background:linear-gradient(145deg,#151e32,#101727); box-shadow:0 12px 28px rgba(0,0,0,.15); }
.metric-label { color:#99a8c6; text-transform:uppercase; letter-spacing:.09em; font-size:.72rem; font-weight:700; }
.metric-value { color:#f3f5ff; font-family:'Segoe UI',Arial,sans-serif; font-size:1.8rem; font-weight:700; margin-top:.45rem; }
.section-kicker { color:#a99dff; text-transform:uppercase; letter-spacing:.12em; font-size:.72rem; font-weight:700; margin:.9rem 0 .3rem; }
.stTextInput > div > div { background:#10182a !important; border:1px solid rgba(148,163,184,.24) !important; border-radius:12px !important; }
[data-testid="stForm"] { border:1px solid var(--line); border-radius:16px; background:linear-gradient(145deg,#141d31,#101727); padding:1.25rem; }
.stTextInput input { color:#f5f7ff !important; }
.stButton > button { border:0 !important; border-radius:12px !important; min-height:2.8rem; color:#fff !important; font-weight:700 !important; background:linear-gradient(100deg,#6757e8,#9363ee) !important; box-shadow:0 9px 24px rgba(103,87,232,.25); transition:filter .15s ease,transform .15s ease; }
.stButton > button:hover { filter:brightness(1.12); transform:translateY(-1px); }
[data-testid="stTabs"] button { color:#aab7d2; font-weight:600; }
[data-testid="stTabs"] button[aria-selected="true"] { color:#c8bfff; }
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:13px; background:rgba(17,26,45,.6); }
[data-testid="stSidebar"] { background:#0c1322; border-right:1px solid var(--line); }
[data-testid="stSidebar"] h2 { font-size:1.15rem; }
code,pre { border-radius:10px !important; }
div[data-testid="stAlert"] { border-radius:12px; }
.small-note { font-size:.82rem; color:#98a7c4; }
</style>
"""


def apply_styles(st) -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)
