import streamlit as st
import geopandas as gpd
import ezdxf
from ezdxf.entities import GeoData
import fiona
import osmnx as ox
import plotly.graph_objects as go
from streamlit_folium import folium_static
import folium
import tempfile
import os

# Konfigurasi Halaman
st.set_page_config(page_title="KML to CAD - Fix Geodata", layout="wide")

def load_kml_properly(path):
    """Membaca semua layer/folder di KML secara mendalam."""
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
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_final(gdf):
    """Konversi ke DXF dengan perbaikan fungsi Geodata dan Vektor Jalan."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Pengaturan Layer
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8})      # Abu-abu
    doc.layers.new(name='KABEL_JARINGAN', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='PERANGKAT_TITIK', dxfattribs={'color': 1}) # Merah

    # 1. AMBIL DATA JALAN (OSM)
    avg_x = gdf.geometry.centroid.x.mean()
    avg_y = gdf.geometry.centroid.y.mean()
    
    try:
        with st.spinner("Menarik data jalan sekitar..."):
            streets = ox.graph_from_point((avg_y, avg_x), dist=600, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            for _, edge in edges.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"Gagal memuat jalan: {e}")

    # 2. SETUP GEODATA (VERSI TERBARU EZDXF)
    # Membuat objek GeoData melalui modelspace
    geo_data = msp.get_geodata() 
    if geo_data is None:
        geo_data = msp.new_geodata()
    
    geo_data.dxf.coordinate_system_definition = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
        'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
        'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,'
        'AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]'
    )
    geo_data.dxf.design_point = (0, 0, 0)
    geo_data.dxf.reference_point = (avg_x, avg_y, 0)
    geo_data.dxf.scale_estimation_method = 1

    # 3. PLOT DATA KML
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'PERANGKAT_TITIK'})
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL_JARINGAN'})
            
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- UI STREAMLIT ---
st.title("📐 KML to DXF Converter (Final Fix)")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)
        if not gdf.empty:
            if st.sidebar.button("💾 Download DXF + Vektor Jalan"):
                dxf_file = convert_to_dxf_final(gdf)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("Klik untuk Simpan DXF", f, file_name="Network_Complete.dxf")

            # Preview Map
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=18)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Google Hybrid').add_to(m)
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'Point':
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                else:
                    folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime').add_to(m)
            folium_static(m, width=1000)
            
    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
    finally:
        if os.path.exists(path): os.unlink(path)
