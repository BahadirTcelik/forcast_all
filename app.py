import streamlit as st
import pandas as pd
import io
import os
import glob
import plotly.graph_objects as go

# ==========================================
# SAYFA AYARLARI
# ==========================================
st.set_page_config(page_title="81 İl İklim Verisi Sentezleyici Pro", layout="wide", page_icon="🌍")

# ==========================================
# GÜVENLİK KİLİDİ (Session State Reset)
# ==========================================
if 'df_kesintisiz' not in st.session_state:
    st.session_state.df_kesintisiz = None

def veriyi_temizle():
    st.session_state.df_kesintisiz = None

# ==========================================
# 0. DİL VE ÇEVİRİ SÖZLÜĞÜ (i18n)
# ==========================================
dil = st.sidebar.radio("🌐 Dil / Language", ["Türkçe", "English"], on_change=veriyi_temizle)

if dil == "Türkçe":
    t = {
        "title": "🌍 Türkiye İklim Verisi Sentezleyici (Downscaling)",
        "desc": "Geçmiş TMY şablonlarını kullanarak, hem tarihsel (2005-2024) hem de gelecek iklim projeksiyonlarını (2025-2053) **dinamik olarak** saatlik verilere dönüştürün. 81 il için çalışır.",
        "sidebar_title": "⚙️ Veri ve Model Ayarları",
        "il_head": "0. İl Seçimi",
        "tmy_head": "1. TMY Şablonu",
        "proj_head": "2. Gelecek Tahmin Ayarları",
        "rcp_opts": {"rcp45": "İyimser (RCP 4.5)", "rcp85": "Kötümser (RCP 8.5)"},
        "btn_calc": "🔥 Tüm Veriyi Sentezle (Geçmiş + Gelecek)",
        "btn_dl": "💾 Hesaplanan Saatlik Veriyi İndir (CSV)",
        "err_tmy": "Bu il için TMY dosyası bulunamadı",
        "no_hist": "Bu il için 2005-2024 tarihsel istasyon verisi bulunmuyor. Sadece 2025-2053 gelecek tahmini gösterilecek.",
    }
else:
    t = {
        "title": "🌍 Turkey Climate Data Synthesizer (Downscaling)",
        "desc": "Dynamically convert both historical (2005-2024) and future scenarios (2025-2053) into hourly data using historical TMY templates. Covers all 81 provinces.",
        "sidebar_title": "⚙️ Data & Model Settings",
        "il_head": "0. Province Selection",
        "tmy_head": "1. TMY Template",
        "proj_head": "2. Future Forecast Settings",
        "rcp_opts": {"rcp45": "Optimistic (RCP 4.5)", "rcp85": "Pessimistic (RCP 8.5)"},
        "btn_calc": "🔥 Synthesize All Data (History + Future)",
        "btn_dl": "💾 Download Hourly Data (CSV)",
        "err_tmy": "No TMY file found for this province",
        "no_hist": "No 2005-2024 historical station data available for this province. Only the 2025-2053 forecast will be shown.",
    }

st.title(t["title"])
st.markdown(t["desc"])
st.divider()

# ==========================================
# 1. İL TABLOSU (kod, istno, gridno, tarihsel_mevcut)
# ==========================================
@st.cache_data
def il_tablosu_yukle():
    return pd.read_csv("il_tablosu.csv")

il_df = il_tablosu_yukle()

# ==========================================
# 2. YAN MENÜ: KULLANICI KONTROL PANELİ
# ==========================================
st.sidebar.header(t["sidebar_title"])

st.sidebar.subheader(t["il_head"])
il_listesi = sorted(il_df['il_adi'].unique())
secilen_il = st.sidebar.selectbox("İl:", il_listesi, on_change=veriyi_temizle)

il_satiri = il_df[il_df['il_adi'] == secilen_il].iloc[0]
kod = il_satiri['kod']
istno = il_satiri['istno']
gridno = il_satiri['gridno']
tarihsel_var = bool(il_satiri['tarihsel_mevcut'])

if not tarihsel_var:
    st.sidebar.warning(t["no_hist"])

st.sidebar.markdown("---")
st.sidebar.subheader(t["tmy_head"])
tmy_dosyalari = sorted(glob.glob(f"TUR_{kod}_*.clm"))
if not tmy_dosyalari:
    st.sidebar.error(f"{t['err_tmy']}: TUR_{kod}_*.clm")
    st.stop()
tmy_secim = st.sidebar.selectbox("TMY Dosyası:", tmy_dosyalari, on_change=veriyi_temizle)

st.sidebar.markdown("---")
st.sidebar.subheader(t["proj_head"])
secilen_model = st.sidebar.selectbox("Model:", ["GFDL", "MPI", "HG"], on_change=veriyi_temizle)
secilen_senaryo = st.sidebar.radio(
    "RCP:",
    options=["rcp45", "rcp85"],
    format_func=lambda x: t["rcp_opts"][x],
    on_change=veriyi_temizle
)
senaryo_sutun = "ort_sck45" if secilen_senaryo == "rcp45" else "ort_sck85"

model_dosya = {"GFDL": "gfdl.csv", "MPI": "mpi.csv", "HG": "hg.csv"}

# ==========================================
# 2b. ANA EKRAN: BİLGİLENDİRME
# ==========================================
col_sol, col_sag = st.columns([1, 1.2])
with col_sol:
    with st.expander(f"ℹ️ {secilen_model} Fiziksel Dinamikleri", expanded=True):
        if dil == "Türkçe":
            if secilen_model == "GFDL": st.write("**GFDL-CM3 (NOAA - ABD):** Uzun vadeli ortalamalarda sapması en düşük modeldir. Takvimi 365 gün (artık yıl Şubat 29 içermez).")
            elif secilen_model == "MPI": st.write("**MPI-ESM (Almanya):** Topografik yapıları en iyi hesaplayan modeldir. Eksiksiz Gregoryen takvim kullanır.")
            else: st.write("**HadGEM2-ES (İngiltere):** Gelecekteki ekstrem sıcak hava dalgalarını en uç sınırlarda simüle eder. 360 günlük takvim kullanır (her ayın 31. günü yoktur).")
        else:
            st.write("Information localized to Turkish.")
    with st.expander(f"🔥 {t['rcp_opts'][secilen_senaryo]}", expanded=True):
        if dil == "Türkçe":
            if secilen_senaryo == "rcp45": st.write("**RCP 4.5:** Emisyonların azaldığı ve sıcaklık artışlarının sınırlandırıldığı senaryo.")
            else: st.write("**RCP 8.5:** Önlemlerin alınmadığı en kötü durum (Business as usual) senaryosu.")
        else:
            st.write("Information localized to Turkish.")

with col_sag:
    st.markdown(f"### 📍 {secilen_il}")
    m1, m2, m3 = st.columns(3)
    m1.metric("İl Kodu", kod)
    m2.metric("İstasyon No", int(istno) if tarihsel_var else "—")
    m3.metric("Grid No", int(gridno))
    st.caption(f"Seçili TMY dosyası: `{tmy_secim}`")

st.divider()

# ==========================================
# 3. BACKEND MOTORU VE HESAPLAMA ALANI
# ==========================================
if st.button(t["btn_calc"], type="primary", use_container_width=True):
    try:
        # --- ADIM 1: TMY Şablonu Çıkarma ---
        with st.spinner("Adım 1: Seçili TMY'den Saatlik Ritim Çıkarılıyor..."):
            sutun_isimleri = ['Diffuse_Solar', 'Temperature', 'Direct_Solar', 'Wind_Speed', 'Wind_Dir', 'Humidity']
            df_tmy = pd.read_csv(tmy_secim, sep=',', skiprows=12, comment='*', names=sutun_isimleri)

            df_tmy.index = pd.date_range(start='2015-01-01 00:00', periods=len(df_tmy), freq='h')
            df_tmy['Temperature'] = df_tmy['Temperature'] / 10
            gunluk_sicaklik_tmy = df_tmy['Temperature'].resample('D').mean()
            df_tmy['Ay'] = df_tmy.index.month
            df_tmy['Gun'] = df_tmy.index.day
            df_tmy['Saat'] = df_tmy.index.hour
            df_tmy['Gunluk_Ort'] = df_tmy.index.floor('D').map(gunluk_sicaklik_tmy)
            df_tmy['Saatlik_Fark'] = df_tmy['Temperature'] - df_tmy['Gunluk_Ort']
            sablon = df_tmy[['Ay', 'Gun', 'Saat', 'Saatlik_Fark']].copy()

        # --- ADIM 2: GEÇMİŞ VERİYİ (2005-2024) SENTEZLEME (varsa) ---
        df_gecmis_final = None
        if tarihsel_var:
            with st.spinner("Adım 2: 2005-2024 Ham Verisine Şablon Giydiriliyor..."):
                df_gecmis_all = pd.read_csv("tarihsel_sicaklik.csv", sep=';')
                df_gecmis = df_gecmis_all[df_gecmis_all['kod'] == kod][['YIL', 'AY', 'GUN', 'ortalama_sicaklik']].copy()
                df_gecmis.columns = ['YIL', 'AY', 'GUN', 'Hedef_Gunluk_Ort']
                df_gecmis['Tarih'] = pd.to_datetime(df_gecmis[['YIL', 'AY', 'GUN']].rename(columns={'YIL': 'year', 'AY': 'month', 'GUN': 'day'}))
                df_gecmis.set_index('Tarih', inplace=True)
                df_gecmis = df_gecmis.sort_index()

                baslangic_hist = df_gecmis.index.min()
                bitis_hist = df_gecmis.index.max() + pd.Timedelta(hours=23)
                saatler_hist = pd.date_range(start=baslangic_hist, end=bitis_hist, freq='h')

                df_sentez_hist = pd.DataFrame(index=saatler_hist)
                df_sentez_hist['Ay'] = df_sentez_hist.index.month
                df_sentez_hist['Gun'] = df_sentez_hist.index.day
                df_sentez_hist['Saat'] = df_sentez_hist.index.hour
                df_sentez_hist.loc[(df_sentez_hist['Ay'] == 2) & (df_sentez_hist['Gun'] == 29), 'Gun'] = 28

                df_sentez_hist = pd.merge(df_sentez_hist, sablon, on=['Ay', 'Gun', 'Saat'], how='left')
                df_sentez_hist.index = saatler_hist
                df_sentez_hist['Hedef_Gunluk_Ort'] = df_sentez_hist.index.floor('D').map(df_gecmis['Hedef_Gunluk_Ort'])
                df_sentez_hist['Sentez_Sicaklik'] = df_sentez_hist['Hedef_Gunluk_Ort'] + df_sentez_hist['Saatlik_Fark']
                df_sentez_hist['Sentez_Sicaklik'] = df_sentez_hist['Sentez_Sicaklik'].interpolate(method='linear').round(3)

                df_gecmis_final = df_sentez_hist[['Sentez_Sicaklik']].reset_index()
                df_gecmis_final.rename(columns={'index': 'Tarih'}, inplace=True)
                df_gecmis_final['Tarih'] = df_gecmis_final['Tarih'].dt.strftime('%Y-%m-%d %H:00')

        # --- ADIM 3: GELECEK VERİYİ SENTEZLEME ---
        with st.spinner("Adım 3: Gelecek Verisine Şablon Giydiriliyor..."):
            future_dosya = model_dosya[secilen_model]
            df_gelecek_all = pd.read_csv(future_dosya, sep=';')
            df_gelecek = df_gelecek_all[df_gelecek_all['gridno'] == gridno].copy()

            df_gelecek.loc[(df_gelecek['AY'] == 2) & (df_gelecek['GUN'] >= 29), 'GUN'] = 28
            df_gelecek = df_gelecek.groupby(['YIL', 'AY', 'GUN']).mean(numeric_only=True).reset_index()
            df_gelecek['Tarih'] = pd.to_datetime(df_gelecek[['YIL', 'AY', 'GUN']].rename(columns={'YIL': 'year', 'AY': 'month', 'GUN': 'day'}))
            df_gelecek.set_index('Tarih', inplace=True)
            df_gelecek = df_gelecek.sort_index()

            baslangic_fut = df_gelecek.index.min()
            bitis_fut = df_gelecek.index.max() + pd.Timedelta(hours=23)
            saatler_fut = pd.date_range(start=baslangic_fut, end=bitis_fut, freq='h')

            df_sentez_fut = pd.DataFrame(index=saatler_fut)
            df_sentez_fut['Ay'] = df_sentez_fut.index.month
            df_sentez_fut['Gun'] = df_sentez_fut.index.day
            df_sentez_fut['Saat'] = df_sentez_fut.index.hour
            df_sentez_fut.loc[(df_sentez_fut['Ay'] == 2) & (df_sentez_fut['Gun'] == 29), 'Gun'] = 28

            df_sentez_fut = pd.merge(df_sentez_fut, sablon, on=['Ay', 'Gun', 'Saat'], how='left')
            df_sentez_fut.index = saatler_fut
            df_sentez_fut['Hedef_Gunluk_Ort'] = df_sentez_fut.index.floor('D').map(df_gelecek[senaryo_sutun])
            df_sentez_fut['Sentez_Sicaklik'] = df_sentez_fut['Hedef_Gunluk_Ort'] + df_sentez_fut['Saatlik_Fark']
            df_sentez_fut['Sentez_Sicaklik'] = df_sentez_fut['Sentez_Sicaklik'].interpolate(method='linear').round(3)

            df_gelecek_final = df_sentez_fut[['Sentez_Sicaklik']].reset_index()
            df_gelecek_final.rename(columns={'index': 'Tarih'}, inplace=True)
            df_gelecek_final['Tarih'] = df_gelecek_final['Tarih'].dt.strftime('%Y-%m-%d %H:00')

        # --- ADIM 4: BİRLEŞTİRME ---
        with st.spinner("Adım 4: Zaman Serisi Hazırlanıyor..."):
            if df_gecmis_final is not None:
                df_kesintisiz = pd.concat([df_gecmis_final, df_gelecek_final], ignore_index=True)
            else:
                df_kesintisiz = df_gelecek_final.copy()
            df_kesintisiz['Tarih_DT'] = pd.to_datetime(df_kesintisiz['Tarih'])
            st.session_state.df_kesintisiz = df_kesintisiz

        st.success(f"🎉 İşlem Tamamlandı! {secilen_il} için toplam {len(df_kesintisiz)} saatlik veri başarıyla sentezlendi.")

    except Exception as e:
        st.error(f"Hata detayı: {str(e)}")

# ==========================================
# 4. GRAFİK VE ANALİZ BÖLÜMÜ (Plotly)
# ==========================================
if st.session_state.df_kesintisiz is not None:
    df_k = st.session_state.df_kesintisiz

    st.markdown("### 📊 Özel Saatlik Profil İncelemesi")
    st.info("Aşağıdan incelemek istediğiniz **tarih aralığını** seçebilirsiniz. Grafik üzerinde fare tekerleği ile yakınlaştırabilir, sürükleyerek kaydırabilirsiniz.")

    min_date = df_k['Tarih_DT'].min().date()
    max_date = df_k['Tarih_DT'].max().date()

    gelecek_veri = df_k[df_k['Tarih_DT'].dt.year > 2024]
    default_start = gelecek_veri['Tarih_DT'].min().date() if not gelecek_veri.empty else min_date
    default_end = default_start + pd.Timedelta(days=7)

    col_d1, col_d2 = st.columns(2)
    start_date = col_d1.date_input("Başlangıç Tarihi:", value=default_start, min_value=min_date, max_value=max_date)
    end_date = col_d2.date_input("Bitiş Tarihi:", value=default_end, min_value=min_date, max_value=max_date)

    mask = (df_k['Tarih_DT'].dt.date >= start_date) & (df_k['Tarih_DT'].dt.date <= end_date)
    filtrelenmis_df = df_k.loc[mask]

    if not filtrelenmis_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtrelenmis_df['Tarih_DT'],
            y=filtrelenmis_df['Sentez_Sicaklik'],
            mode='lines',
            line=dict(color='#FF4B4B', width=2),
            name=secilen_il,
            hovertemplate='%{x|%Y-%m-%d %H:%M}<br>%{y:.2f} °C<extra></extra>'
        ))
        fig.update_layout(
            height=450,
            xaxis_title='Zaman Çizelgesi',
            yaxis_title='Sıcaklık (°C)',
            hovermode='x unified',
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Lütfen geçerli bir tarih aralığı seçin.")

    st.divider()
    df_download = df_k.drop(columns=['Tarih_DT'])
    csv_buffer = io.StringIO()
    df_download.to_csv(csv_buffer, index=False, sep=';', decimal=',')

    st.download_button(
        label=t["btn_dl"],
        data=csv_buffer.getvalue(),
        file_name=f"Sentez_{kod}_{secilen_model}_{secilen_senaryo}.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True
    )
