import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import plotly.graph_objects as go
from streamlit_folium import folium_static
import folium
import tempfile
import os
from shapely.geometry import Point, LineString

# Konfigurasi Halaman
st.set_page_config(page_title="KML to CAD - Autovector Road", layout="wide")

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
        # Filter hanya Point dan LineString (mengabaikan Polygon area)
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_with_roads(gdf):
    """Konversi ke DXF dengan tambahan vektor jalan dari OSM."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8})      # Abu-abu (Roads)
    doc.layers.new(name='KABEL_JARINGAN', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='PERANGKAT_TITIK', dxfattribs={'color': 1}) # Merah
    doc.layers.new(name='LABEL_NAME', dxfattribs={'color': 7})     # Putih

    # 1. AMBIL DATA JALAN (OSM)
    avg_x = gdf.geometry.centroid.x.mean()
    avg_y = gdf.geometry.centroid.y.mean()
    
    try:
        # Mengunduh jaringan jalan dalam radius 600m dari titik tengah KML
        with st.spinner("Mengunduh data vektor jalan di sekitar area..."):
            streets = ox.graph_from_point((avg_y, avg_x), dist=600, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            
            for _, edge in edges.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    # Masukkan ke layer MAP_JALAN
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"Gagal memuat vektor jalan: {e}")

    # 2. MASUKKAN DATA JARINGAN (KML)
    for _, row in gdf.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        
        if geom.geom_type == 'Point':
            # Gambar perangkat (ODP/Tiang)
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'PERANGKAT_TITIK'})
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={
                    'layer': 'LABEL_NAME', 
                    'height': 0.00006
                }).set_placement((geom.x, geom.y))
        
        elif geom.geom_type == 'LineString':
            # Gambar jalur kabel
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL_JARINGAN'})
            
    tmp_dxf = tempfile.NamedTemporaryFile(delete=False, suffix='.dxf')
    doc.saveas(tmp_dxf.name)
    return tmp_dxf.name

# --- ANTARMUKA PENGGUNA (UI) ---

st.title("📐 KML to DXF + Vektor Jalan Otomatis")
st.info("Aplikasi ini akan menarik data jalan dari OpenStreetMap dan memasukkannya ke file DXF Anda.")

uploaded_file = st.sidebar.file_uploader("Upload File KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)

        if gdf.empty:
            st.error("Data KML tidak valid atau kosong.")
        else:
            st.sidebar.success(f"Ditemukan {len(gdf)} objek jaringan.")
            
            # Tombol Download
            if st.sidebar.button("🚀 Generate DXF + Jalan"):
                dxf_path = convert_to_dxf_with_roads(gdf)
                with open(dxf_path, "rb") as file:
                    st.sidebar.download_button(
                        label="📥 Download File DXF",
                        data=file,
                        file_name="Jaringan_dan_Peta_Jalan.dxf",
                        mime="application/dxf"
                    )

            # Preview Tabs
            tab1, tab2 = st.tabs(["📍 Peta Lokasi", "📐 Preview Skematik"])
            
            with tab1:
                # Preview Map dengan Basemap Satelit & Jalan
                center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=18)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Hybrid').add_to(m)
                
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'Point':
                        folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                    elif row.geometry.geom_type == 'LineString':
                        points = [[p[1], p[0]] for p in row.geometry.coords]
                        folium.PolyLine(points, color='lime', weight=3).add_to(m)
                folium_static(m, width=1000)

            with tab2:
                # Preview Skematik Sederhana
                fig = go.Figure()
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'LineString':
                        x, y = row.geometry.xy
                        fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines', line=dict(color='lime')))
                    elif row.geometry.geom_type == 'Point':
                        fig.add_trace(go.Scatter(x=[row.geometry.x], y=[row.geometry.y], mode='markers', 
                                                 marker=dict(color='red', size=6)))
                fig.update_layout(plot_bgcolor='black', paper_bgcolor='black', font_color='white',
                                 xaxis=dict(showgrid=False, zeroline=False), yaxis=dict(scaleanchor="x"))
                st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Terjadi kesalahan teknis: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)
