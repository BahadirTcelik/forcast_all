import streamlit as st
import pandas as pd
import io
import glob
import plotly.graph_objects as go

# ==========================================
# SAYFA AYARLARI
# ==========================================

# ==========================================
# GÜVENLİK KİLİDİ (Session State Reset)
# ==========================================
if 'nem_df' not in st.session_state:
    st.session_state.nem_df = None
if 'nem_tmy_ref_df' not in st.session_state:
    st.session_state.nem_tmy_ref_df = None
if 'nem_tarihsel_ref_df' not in st.session_state:
    st.session_state.nem_tarihsel_ref_df = None

def veriyi_temizle():
    st.session_state.nem_df = None
    st.session_state.nem_tmy_ref_df = None
    st.session_state.nem_tarihsel_ref_df = None

st.title("💧 Türkiye Nem Verisi Sentezleyici (Downscaling)")
st.markdown("Geçmiş TMY şablonlarını kullanarak, hem tarihsel (2005-2024) hem de gelecek nem projeksiyonlarını (2025-2053) **dinamik olarak** saatlik **bağıl nem (%)** verilerine dönüştürün. 81 il için çalışır. *Sıcaklık ile aynı delta/shape yöntemi; nem değerleri %0-100 aralığına kırpılır.*")
st.divider()

# ==========================================
# 1. İL TABLOSU
# ==========================================
@st.cache_data
def il_tablosu_yukle():
    return pd.read_csv("il_tablosu.csv")

il_df = il_tablosu_yukle()

# ==========================================
# 2. YAN MENÜ
# ==========================================
st.sidebar.header("⚙️ Nem Veri ve Model Ayarları")

st.sidebar.subheader("0. İl Seçimi")
il_listesi = sorted(il_df['il_adi'].unique())
secilen_il = st.sidebar.selectbox("İl:", il_listesi, on_change=veriyi_temizle)

il_satiri = il_df[il_df['il_adi'] == secilen_il].iloc[0]
kod = il_satiri['kod']
istno = il_satiri['istno']
gridno = il_satiri['gridno']
tarihsel_var = bool(il_satiri['tarihsel_mevcut'])

if not tarihsel_var:
    st.sidebar.warning("Bu il için 2005-2024 tarihsel istasyon nem verisi bulunmuyor. Sadece 2025-2053 gelecek tahmini gösterilecek.")

st.sidebar.markdown("---")
st.sidebar.subheader("1. TMY Şablonu")
tmy_dosyalari = sorted(glob.glob(f"TUR_{kod}_*.clm"))
if not tmy_dosyalari:
    st.sidebar.error(f"Bu il için TMY dosyası bulunamadı: TUR_{kod}_*.clm")
    st.stop()
tmy_secim = st.sidebar.selectbox("TMY Dosyası:", tmy_dosyalari, on_change=veriyi_temizle)

st.sidebar.markdown("---")
st.sidebar.subheader("2. Gelecek Tahmin Ayarları")
secilen_model = st.sidebar.selectbox("Model:", ["GFDL", "MPI", "HG"], on_change=veriyi_temizle)
secilen_senaryo = st.sidebar.radio(
    "RCP:",
    options=["rcp45", "rcp85"],
    format_func=lambda x: {"rcp45": "İyimser (RCP 4.5)", "rcp85": "Kötümser (RCP 8.5)"}[x],
    on_change=veriyi_temizle
)
senaryo_sutun = "nem45" if secilen_senaryo == "rcp45" else "nem85"
model_dosya = {"GFDL": "gfdl", "MPI": "mpi", "HG": "hg"}

@st.cache_data
def parcali_csv_oku(prefix, sep=';'):
    """Parçalara bölünmüş (prefix_part1.csv, ...) CSV'leri okuyup birleştirir.
    Bölünmemiş 'prefix.csv' varsa onu kullanır."""
    parcalar = sorted(glob.glob(f"{prefix}_part*.csv"))
    if parcalar:
        return pd.concat([pd.read_csv(p, sep=sep) for p in parcalar], ignore_index=True)
    return pd.read_csv(f"{prefix}.csv", sep=sep)


def istno_nem_kontrol(df_tarihsel, kod, istno):
    """İstasyon numarasına göre tarihsel nem verisinin sağlığını kontrol eder."""
    gerekli = {'ortalama_nem', 'istno', 'kod', 'YIL', 'AY', 'GUN'}
    eksik = gerekli - set(df_tarihsel.columns)
    if eksik:
        return False, (f"Veri dosyasında eksik kolon(lar): {', '.join(sorted(eksik))}. "
                       f"Streamlit Cloud'da 'Manage app' > 'Reboot app' yapın.")
    dfx = df_tarihsel[(df_tarihsel['kod'] == kod) & (df_tarihsel['istno'] == istno)]
    if dfx.empty:
        return False, f"İstasyon {istno} ({kod}) tarihsel nem verisinde bulunamadı."
    if dfx['ortalama_nem'].notna().sum() == 0:
        return False, f"İstasyon {istno} ({kod}) için nem sütunu tamamen boş."
    return True, "OK"

# ==========================================
# 2b. BİLGİLENDİRME
# ==========================================
col_sag, = st.columns(1)
with col_sag:
    st.markdown(f"### 📍 {secilen_il}")
    m1, m2, m3 = st.columns(3)
    m1.metric("İl Kodu", kod)
    m2.metric("İstasyon No", int(istno) if tarihsel_var else "—")
    m3.metric("Grid No", int(gridno))
    st.caption(f"Seçili TMY dosyası: `{tmy_secim}`  |  Model: **{secilen_model}**  |  Senaryo: **{secilen_senaryo.upper()}**")

st.divider()

# ==========================================
# 3. HESAPLAMA
# ==========================================
if st.button("💧 Tüm Nem Verisini Sentezle (Geçmiş + Gelecek)", type="primary", use_container_width=True):
    try:
        # --- ADIM 1: TMY'den Saatlik Nem Ritmi ---
        with st.spinner("Adım 1: Seçili TMY'den Saatlik Nem Ritmi Çıkarılıyor..."):
            sutun_isimleri = ['Diffuse_Solar', 'Temperature', 'Direct_Solar', 'Wind_Speed', 'Wind_Dir', 'Humidity']
            df_tmy = pd.read_csv(tmy_secim, sep=',', skiprows=12, comment='*', names=sutun_isimleri)
            df_tmy.index = pd.date_range(start='2015-01-01 00:00', periods=len(df_tmy), freq='h')
            # Nem zaten yüzde; ölçekleme yok
            gunluk_nem_tmy = df_tmy['Humidity'].resample('D').mean()
            df_tmy['Ay'] = df_tmy.index.month
            df_tmy['Gun'] = df_tmy.index.day
            df_tmy['Saat'] = df_tmy.index.hour
            df_tmy['Gunluk_Ort'] = df_tmy.index.floor('D').map(gunluk_nem_tmy)
            df_tmy['Saatlik_Fark'] = df_tmy['Humidity'] - df_tmy['Gunluk_Ort']
            sablon = df_tmy[['Ay', 'Gun', 'Saat', 'Saatlik_Fark', 'Humidity']].rename(columns={'Humidity': 'TMY_Nem'}).copy()

            # TMY nem kalite kontrolü: bazı TMY dosyalarının nem kolonu gün-içi sabittir
            # (bozuk EPW dönüşümü). Bu durumda saatlik ritim düz olur, nem ~ günlük ortalama.
            fark_std = df_tmy['Saatlik_Fark'].std()
            if fark_std < 1.0:
                st.warning(
                    f"⚠️ Seçili TMY dosyasının nem kolonu gün-içi neredeyse sabit "
                    f"(saatlik sapma std={fark_std:.2f}). Bu dosya için saatlik nem ritmi "
                    f"düz kalacak (saatlik nem ≈ günlük ortalama). Daha gerçekçi gün/gece "
                    f"nem dalgalanması için bu ilin başka bir TMY dosyasını deneyin."
                )

        # --- ADIM 2: GEÇMİŞ NEM (2005-2024) ---
        df_gecmis_final = None
        df_gecmis_all = None
        if tarihsel_var:
            with st.spinner("Adım 2: 2005-2024 Ham Nem Verisine Şablon Giydiriliyor..."):
                df_gecmis_all = parcali_csv_oku("tarihsel_nem")
                df_gecmis = df_gecmis_all[df_gecmis_all['kod'] == kod][['YIL', 'AY', 'GUN', 'ortalama_nem']].copy()
                df_gecmis.columns = ['YIL', 'AY', 'GUN', 'Hedef_Gunluk_Ort']
                df_gecmis['Tarih'] = pd.to_datetime(df_gecmis[['YIL', 'AY', 'GUN']].rename(columns={'YIL': 'year', 'AY': 'month', 'GUN': 'day'}))
                df_gecmis.set_index('Tarih', inplace=True)
                df_gecmis = df_gecmis.sort_index()

                baslangic = df_gecmis.index.min()
                bitis = df_gecmis.index.max() + pd.Timedelta(hours=23)
                saatler = pd.date_range(start=baslangic, end=bitis, freq='h')

                df_s = pd.DataFrame(index=saatler)
                df_s['Ay'] = df_s.index.month
                df_s['Gun'] = df_s.index.day
                df_s['Saat'] = df_s.index.hour
                df_s.loc[(df_s['Ay'] == 2) & (df_s['Gun'] == 29), 'Gun'] = 28
                df_s = pd.merge(df_s, sablon, on=['Ay', 'Gun', 'Saat'], how='left')
                df_s.index = saatler
                df_s['Hedef_Gunluk_Ort'] = df_s.index.floor('D').map(df_gecmis['Hedef_Gunluk_Ort'])
                df_s['Sentez_Nem'] = df_s['Hedef_Gunluk_Ort'] + df_s['Saatlik_Fark']
                df_s['Sentez_Nem'] = df_s['Sentez_Nem'].interpolate(method='linear').clip(0, 100).round(2)

                df_gecmis_final = df_s[['Sentez_Nem', 'TMY_Nem']].reset_index()
                df_gecmis_final.rename(columns={'index': 'Tarih'}, inplace=True)
                df_gecmis_final['Tarih'] = df_gecmis_final['Tarih'].dt.strftime('%Y-%m-%d %H:00')

        # --- ADIM 3: GELECEK NEM ---
        with st.spinner("Adım 3: Gelecek Nem Verisine Şablon Giydiriliyor..."):
            future_dosya = model_dosya[secilen_model] + "_nem"
            df_gelecek_all = parcali_csv_oku(future_dosya)
            df_gelecek = df_gelecek_all[df_gelecek_all['gridno'] == gridno].copy()
            df_gelecek.loc[(df_gelecek['AY'] == 2) & (df_gelecek['GUN'] >= 29), 'GUN'] = 28
            df_gelecek = df_gelecek.groupby(['YIL', 'AY', 'GUN']).mean(numeric_only=True).reset_index()
            df_gelecek['Tarih'] = pd.to_datetime(df_gelecek[['YIL', 'AY', 'GUN']].rename(columns={'YIL': 'year', 'AY': 'month', 'GUN': 'day'}))
            df_gelecek.set_index('Tarih', inplace=True)
            df_gelecek = df_gelecek.sort_index()

            baslangic = df_gelecek.index.min()
            bitis = df_gelecek.index.max() + pd.Timedelta(hours=23)
            saatler = pd.date_range(start=baslangic, end=bitis, freq='h')

            df_s = pd.DataFrame(index=saatler)
            df_s['Ay'] = df_s.index.month
            df_s['Gun'] = df_s.index.day
            df_s['Saat'] = df_s.index.hour
            df_s.loc[(df_s['Ay'] == 2) & (df_s['Gun'] == 29), 'Gun'] = 28
            df_s = pd.merge(df_s, sablon, on=['Ay', 'Gun', 'Saat'], how='left')
            df_s.index = saatler
            df_s['Hedef_Gunluk_Ort'] = df_s.index.floor('D').map(df_gelecek[senaryo_sutun])
            df_s['Sentez_Nem'] = df_s['Hedef_Gunluk_Ort'] + df_s['Saatlik_Fark']
            df_s['Sentez_Nem'] = df_s['Sentez_Nem'].interpolate(method='linear').clip(0, 100).round(2)

            df_gelecek_final = df_s[['Sentez_Nem', 'TMY_Nem']].reset_index()
            df_gelecek_final.rename(columns={'index': 'Tarih'}, inplace=True)
            df_gelecek_final['Tarih'] = df_gelecek_final['Tarih'].dt.strftime('%Y-%m-%d %H:00')

        # --- ADIM 4: BİRLEŞTİRME ---
        with st.spinner("Adım 4: Zaman Serisi Hazırlanıyor..."):
            if df_gecmis_final is not None:
                nem_df = pd.concat([df_gecmis_final, df_gelecek_final], ignore_index=True)
            else:
                nem_df = df_gelecek_final.copy()
            nem_df['Tarih_DT'] = pd.to_datetime(nem_df['Tarih'])
            st.session_state.nem_df = nem_df

        # --- REFERANS 1: TMY NEM (tüm eksene duplicate, zaten TMY_Nem sütununda) ---
        st.session_state.nem_tmy_ref_df = nem_df[['Tarih_DT', 'TMY_Nem']].copy()

        # --- REFERANS 2: TARİHSEL ORTALAMA NEM (2005-2024, gün-bazında ort, tüm eksene) ---
        if tarihsel_var and df_gecmis_all is not None:
            with st.spinner("Adım 5: Tarihsel Ortalama Nem Referansı Hazırlanıyor..."):
                saglikli, mesaj = istno_nem_kontrol(df_gecmis_all, kod, istno)
                if not saglikli:
                    st.warning(f"⚠️ Tarihsel nem referansı hesaplanamadı ({secilen_il}, istno={istno}): {mesaj}")
                    st.session_state.nem_tarihsel_ref_df = None
                else:
                    dfh = df_gecmis_all[(df_gecmis_all['kod'] == kod) & (df_gecmis_all['istno'] == istno)][['AY', 'GUN', 'ortalama_nem']].copy()
                    ort_gun = dfh.groupby(['AY', 'GUN'])['ortalama_nem'].mean().reset_index()
                    ort_gun.columns = ['AY', 'GUN', 'Tarihsel_Nem_Ref']
                    gunler = pd.date_range(nem_df['Tarih_DT'].min().normalize(), nem_df['Tarih_DT'].max().normalize(), freq='D')
                    gunluk = pd.DataFrame({'Tarih_DT': gunler})
                    gunluk['AY'] = gunluk['Tarih_DT'].dt.month
                    gunluk['GUN'] = gunluk['Tarih_DT'].dt.day
                    gunluk = gunluk.merge(ort_gun, on=['AY', 'GUN'], how='left')
                    st.session_state.nem_tarihsel_ref_df = gunluk[['Tarih_DT', 'Tarihsel_Nem_Ref']]
        else:
            st.session_state.nem_tarihsel_ref_df = None

        st.success(f"🎉 İşlem Tamamlandı! {secilen_il} için toplam {len(nem_df)} saatlik nem verisi sentezlendi.")

    except Exception as e:
        st.error(f"Hata detayı: {str(e)}")

# ==========================================
# 4. GRAFİK (Plotly)
# ==========================================
if st.session_state.nem_df is not None:
    df_k = st.session_state.nem_df

    st.markdown("### 📊 Özel Saatlik Nem Profili İncelemesi")
    st.info("İncelemek istediğiniz **tarih aralığını** seçin. Grafik üzerinde fare tekerleği ile yakınlaştırabilir, sürükleyerek kaydırabilirsiniz.")

    min_date = df_k['Tarih_DT'].min().date()
    max_date = df_k['Tarih_DT'].max().date()
    gelecek_veri = df_k[df_k['Tarih_DT'].dt.year > 2024]
    default_start = gelecek_veri['Tarih_DT'].min().date() if not gelecek_veri.empty else min_date
    default_end = default_start + pd.Timedelta(days=7)

    col_d1, col_d2 = st.columns(2)
    start_date = col_d1.date_input("Başlangıç Tarihi:", value=default_start, min_value=min_date, max_value=max_date)
    end_date = col_d2.date_input("Bitiş Tarihi:", value=default_end, min_value=min_date, max_value=max_date)

    tarihsel_ref_mevcut = st.session_state.nem_tarihsel_ref_df is not None
    col_s1, col_s2 = st.columns(2)
    tmy_goster = col_s1.checkbox("📐 TMY Nem Referans Çizgisini Göster", value=False)
    tarihsel_ref_goster = col_s2.checkbox(
        "📅 Tarihsel Ortalama Nem (2005-2024, duplicate)",
        value=False,
        disabled=not tarihsel_ref_mevcut
    )
    if not tarihsel_ref_mevcut:
        col_s2.caption("Bu il için tarihsel ortalama nem verisi yok.")

    mask = (df_k['Tarih_DT'].dt.date >= start_date) & (df_k['Tarih_DT'].dt.date <= end_date)
    filtrelenmis_df = df_k.loc[mask]

    if not filtrelenmis_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtrelenmis_df['Tarih_DT'], y=filtrelenmis_df['Sentez_Nem'],
            mode='lines', line=dict(color='#1CA9C9', width=2), name=f"{secilen_il} Nem",
            hovertemplate='%{x|%Y-%m-%d %H:%M}<br>%{y:.1f} %<extra></extra>'
        ))
        if tmy_goster:
            fig.add_trace(go.Scatter(
                x=filtrelenmis_df['Tarih_DT'], y=filtrelenmis_df['TMY_Nem'],
                mode='lines', line=dict(color='#8888FF', width=1.5, dash='dash'), name='TMY Nem Referans',
                hovertemplate='%{x|%Y-%m-%d %H:%M}<br>TMY: %{y:.1f} %<extra></extra>'
            ))
        if tarihsel_ref_goster and tarihsel_ref_mevcut:
            tr = st.session_state.nem_tarihsel_ref_df
            tr_mask = (tr['Tarih_DT'].dt.date >= start_date) & (tr['Tarih_DT'].dt.date <= end_date)
            tr_f = tr.loc[tr_mask]
            fig.add_trace(go.Scatter(
                x=tr_f['Tarih_DT'], y=tr_f['Tarihsel_Nem_Ref'],
                mode='lines', line=dict(color='#2ECC71', width=1.5, dash='dashdot'),
                name='Tarihsel Ort. Nem (2005-2024)',
                hovertemplate='%{x|%Y-%m-%d}<br>Tarihsel Ort: %{y:.1f} %<extra></extra>'
            ))
        fig.update_layout(
            height=450, xaxis_title='Zaman Çizelgesi', yaxis_title='Bağıl Nem (%)',
            yaxis=dict(range=[0, 100]), hovermode='x unified',
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Lütfen geçerli bir tarih aralığı seçin.")

    st.divider()
    df_download = df_k.drop(columns=['Tarih_DT'])
    csv_buffer = io.StringIO()
    df_download.to_csv(csv_buffer, index=False, sep=';', decimal=',')
    st.download_button(
        label="💾 Hesaplanan Saatlik Nem Verisini İndir (CSV)",
        data=csv_buffer.getvalue(),
        file_name=f"Nem_{kod}_{secilen_model}_{secilen_senaryo}.csv",
        mime="text/csv", type="primary", use_container_width=True
    )
