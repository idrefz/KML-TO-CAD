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
st.set_page_config(page_title="KML to CAD Geodata Fix", layout="wide")

def load_kml_properly(path):
    """Membaca semua folder di KML secara mendalam."""
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
        # Filter hanya Point dan LineString (Abaikan Polygon)
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_final(gdf):
    """Konversi ke DXF dengan integrasi Vektor Jalan & Geodata Terbaru."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8})      # Abu-abu
    doc.layers.new(name='KABEL_JARINGAN', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='PERANGKAT_TITIK', dxfattribs={'color': 1}) # Merah
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7})      # Putih

    # 1. AMBIL DATA JALAN (OSM)
    avg_x = gdf.geometry.centroid.x.mean()
    avg_y = gdf.geometry.centroid.y.mean()
    
    try:
        with st.spinner("Menarik data jalan sekitar..."):
            # Radius 600m dari pusat jaringan
            streets = ox.graph_from_point((avg_y, avg_x), dist=600, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            for _, edge in edges.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"Info: Vektor jalan tidak termuat ({e})")

    # 2. SETUP GEODATA (FIX ERROR: new_entity)
    # Cara baru untuk ezdxf versi terbaru
    geo_data = msp.get_geodata() 
    if geo_data is None:
        geo_data = msp.new_geodata()
    
    # Set referensi lokasi agar AutoCAD tahu ini koordinat bumi
    geo_data.dxf.coordinate_system_definition = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
    )
    geo_data.dxf.design_point = (0, 0, 0)
    geo_data.dxf.reference_point = (avg_x, avg_y, 0)
    geo_data.dxf.scale_estimation_method = 1

    # 3. PLOT DATA KML (Kabel & Titik)
    for _, row in gdf.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'PERANGKAT_TITIK'})
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 0.00007}).set_placement((geom.x, geom.y))
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL_JARINGAN'})
            
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- ANTARMUKA UTAMA (UI) ---

st.title("📐 KML to DXF Professional (Final Fix)")
st.markdown("Fitur: **Auto-Road Vectors**, **Georeferenced**, & **Deep KML Scan**.")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        # Load data
        gdf = load_kml_properly(path)
        
        if not gdf.empty:
            st.sidebar.success(f"Ditemukan {len(gdf)} Objek Jaringan")
            
            # --- TOMBOL DOWNLOAD ---
            if st.sidebar.button("🚀 Generate & Download DXF"):
                with st.spinner("Memproses file DXF..."):
                    dxf_file_path = convert_to_dxf_final(gdf)
                    with open(dxf_file_path, "rb") as f:
                        st.sidebar.download_button(
                            label="📥 Klik untuk Simpan DXF",
                            data=f,
                            file_name="Hasil_Jaringan_Lengkap.dxf",
                            mime="application/dxf"
                        )
            
            # --- VISUALISASI ---
            tab1, tab2 = st.tabs(["📍 Peta Lokasi (Satellite Hybrid)", "📐 Preview Skematik"])
            
            with tab1:
                center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=18)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Hybrid').add_to(m)
                
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'Point':
                        folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                    else:
                        folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
                folium_static(m, width=1000)

            with tab2:
                fig = go.Figure()
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'LineString':
                        x, y = row.geometry.xy
                        fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines', line=dict(color='lime')))
                    elif row.geometry.geom_type == 'Point':
                        fig.add_trace(go.Scatter(x=[row.geometry.x], y=[row.geometry.y], mode='markers', marker=dict(color='red')))
                fig.update_layout(plot_bgcolor='black', paper_bgcolor='black', font_color='white',
                                 xaxis=dict(showgrid=False, zeroline=False), yaxis=dict(scaleanchor="x"))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("KML tidak berisi data Point atau LineString yang terbaca.")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)
