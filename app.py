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
st.set_page_config(page_title="KML to CAD Professional", layout="wide")

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
    """Konversi ke DXF dengan penanganan GEODATA yang kompatibel."""
    # PENTING: Gunakan versi R2010 untuk mendukung GEODATA
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8})
    doc.layers.new(name='KABEL_JARINGAN', dxfattribs={'color': 3})
    doc.layers.new(name='PERANGKAT_TITIK', dxfattribs={'color': 1})
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7})

    avg_x = gdf.geometry.centroid.x.mean()
    avg_y = gdf.geometry.centroid.y.mean()
    
    # 1. AMBIL DATA JALAN (OSM)
    try:
        with st.spinner("Menarik data jalan sekitar..."):
            streets = ox.graph_from_point((avg_y, avg_x), dist=600, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            for _, edge in edges.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"Info: Vektor jalan tidak termuat ({e})")

    # 2. SETUP GEODATA (DENGAN TRY-EXCEPT UNTUK KEAMANAN)
    try:
        geo_data = msp.get_geodata()
        if geo_data is None:
            geo_data = msp.new_geodata()
        
        # Menggunakan metode set_coordinate_system jika atribut langsung gagal
        # Ini mendefinisikan WGS84 secara eksplisit
        wgs84 = (
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
        )
        
        # Set properti dasar yang didukung semua versi R2010+
        geo_data.dxf.design_point = (0, 0, 0)
        geo_data.dxf.reference_point = (avg_x, avg_y, 0)
        
        # Coba set definisi sistem koordinat secara manual
        if hasattr(geo_data.dxf, 'coordinate_system_definition'):
            geo_data.dxf.coordinate_system_definition = wgs84
    except Exception as e:
        st.sidebar.error(f"Gagal mengatur Geodata: {e}")

    # 3. PLOT DATA KML
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

# --- UI STREAMLIT ---

st.title("📐 KML to DXF Professional (Final Fix)")
st.markdown("Fitur: **Vektor Jalan OSM**, **Georeferenced**, & **Tanpa Polygon**.")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)
        
        if not gdf.empty:
            st.sidebar.success(f"Ditemukan {len(gdf)} Objek")
            
            if st.sidebar.button("🚀 Generate & Download DXF"):
                with st.spinner("Memproses file DXF..."):
                    dxf_file_path = convert_to_dxf_final(gdf)
                    with open(dxf_file_path, "rb") as f:
                        st.sidebar.download_button(
                            label="📥 Klik untuk Simpan DXF",
                            data=f,
                            file_name="Hasil_Konversi_Lengkap.dxf",
                            mime="application/dxf"
                        )
            
            # Preview Map
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
        else:
            st.error("KML tidak berisi data Point atau LineString yang valid.")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)
