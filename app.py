import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import folium
import plotly.graph_objects as go
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML to CAD Fix", layout="wide")

# --- FUNGSI HELPER ---

def load_kml_properly(path):
    """Membaca semua layer/folder di KML secara paksa."""
    layers = fiona.listlayers(path)
    gdfs = []
    for layer in layers:
        try:
            tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
            if not tmp_gdf.empty:
                gdfs.append(tmp_gdf)
        except:
            continue
    if gdfs:
        full_gdf = gpd.pd.concat(gdfs, ignore_index=True)
        # Filter hanya Point dan LineString
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_kml_to_dxf(gdf):
    """Fungsi untuk mengonversi GeoDataFrame ke file DXF sementara."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.00003)
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords))
            
    tmp_dxf = tempfile.NamedTemporaryFile(delete=False, suffix='.dxf')
    doc.saveas(tmp_dxf.name)
    return tmp_dxf.name

# --- UI UTAMA ---

st.title("📐 KML to DXF (Fix Deep Folders)")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        # 1. Ambil data
        gdf = load_kml_properly(path)

        if gdf.empty:
            st.sidebar.error("Gagal mengekstrak data dari KML ini.")
            st.error("Data tidak ditemukan atau tidak valid.")
        else:
            # 2. Tampilkan Info & Tombol Download di Sidebar
            st.sidebar.success(f"Terdeteksi {len(gdf)} objek valid.")
            
            # Buat file DXF saat tombol ditekan
            if st.sidebar.button("💾 Proses ke DXF"):
                dxf_path = convert_kml_to_dxf(gdf)
                with open(dxf_path, "rb") as file:
                    st.sidebar.download_button(
                        label="📥 Klik untuk Download DXF",
                        data=file,
                        file_name="hasil_konversi.dxf",
                        mime="application/dxf"
                    )
                # Opsional: Hapus file temporary setelah diproses
                # os.unlink(dxf_path)

            # 3. Visualisasi Tab
            st.success(f"Berhasil membaca {len(gdf)} objek (Point & LineString).")
            tab1, tab2 = st.tabs(["📍 Peta Lokasi", "📐 Skematik Jaringan"])
            
            with tab1:
                center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=18)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Satellite').add_to(m)
                
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'Point':
                        folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                    elif row.geometry.geom_type == 'LineString':
                        points = [[p[1], p[0]] for p in row.geometry.coords]
                        folium.PolyLine(points, color='lime', weight=3).add_to(m)
                folium_static(m, width=1000)

            with tab2:
                fig = go.Figure()
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'LineString':
                        x, y = row.geometry.xy
                        fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines', line=dict(color='lime')))
                    elif row.geometry.geom_type == 'Point':
                        fig.add_trace(go.Scatter(x=[row.geometry.x], y=[row.geometry.y], mode='markers+text', 
                                                 text=[row.get('Name','')], textfont=dict(color="white")))
                fig.update_layout(plot_bgcolor='black', paper_bgcolor='black', font_color='white',
                                 xaxis=dict(showgrid=False, zeroline=False), yaxis=dict(scaleanchor="x"))
                st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error sistem: {e}")
    finally:
        # Hapus file KML sementara
        if os.path.exists(path):
            os.unlink(path)
