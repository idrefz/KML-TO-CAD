import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import folium
import plotly.graph_objects as go
from streamlit_folium import folium_static
import tempfile
import os

st.set_page_config(page_title="KML to CAD Fix", layout="wide")

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
    return gpd.pd.concat(gdfs, ignore_index=True) if gdfs else gpd.GeoDataFrame()

st.title("📐 KML to DXF (Fix Deep Folders)")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name
# Di dalam bagian 'if uploaded_file:'
gdf = load_all_kml_layers(path)

if not gdf.empty:
    st.sidebar.success(f"Terdeteksi {len(gdf)} objek valid.")
    
    # Tombol untuk memicu pembuatan file DXF
    if st.sidebar.button("💾 Proses ke DXF"):
        dxf_path = convert_kml_to_dxf(gdf) # Fungsi konversi Anda
        
        with open(dxf_path, "rb") as file:
            st.sidebar.download_button(
                label="📥 Klik untuk Download DXF",
                data=file,
                file_name="hasil_konversi.dxf",
                mime="application/dxf"
            )
else:
    st.sidebar.error("Gagal mengekstrak data Point atau LineString dari KML ini.")

    try:
        # Menggunakan fungsi pembacaan mendalam
        gdf_raw = load_kml_properly(path)
        
        # Filter: Hanya Point dan LineString (Abaikan Polygon)
        gdf = gdf_raw[gdf_raw.geometry.type.isin(['Point', 'LineString'])].copy()

        if gdf.empty:
            st.error("Data tetap tidak terbaca. Pastikan KML bukan file kosong.")
        else:
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
