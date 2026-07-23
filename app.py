import streamlit as st

st.set_page_config(page_title="81 İl İklim & Nem Sentezleyici", layout="wide", page_icon="🌍")

pg = st.navigation([
    st.Page("sicaklik.py", title="Sıcaklık", icon="🌡️", default=True),
    st.Page("1_Nem.py", title="Nem", icon="💧"),
])
pg.run()
