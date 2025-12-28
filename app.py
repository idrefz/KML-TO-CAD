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

st.set_page_config(page_title="KML to CAD Georeferenced", layout="wide")

def load_kml_all_layers(path):
    """Membaca semua folder di KML (ODP, Kabel, Alpro)."""
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
        # Ambil Point dan LineString, abaikan Polygon agar tidak menutupi peta
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_with_georef(gdf):
    """Konversi ke DXF dengan sistem koordinat bumi (WGS84)."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Layering
    doc.layers.new(name='KABEL', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='ODP_TIANG', dxfattribs={'color': 1}) # Merah
    
    # Ambil titik tengah untuk Georeference
    avg_x = gdf.geometry.centroid.x.mean()
    avg_y = gdf.geometry.centroid.y.mean()

    # --- SCRIPT GEOLOCATION (PENTING) ---
    # Memberi tahu AutoCAD bahwa koordinat di file ini adalah koordinat Bumi (Long/Lat)
    geo_data = doc.entitydb.new_entity('GEODATA', dxfattribs={
        'version': 2,
        'coordinate_system_definition': 'GEOGRAPHIC',
        'coordinate_system_name': 'WGS84', # Standar KML/GPS
        'design_point': (0, 0, 0),
        'reference_point': (avg_x, avg_y, 0),
        'horizontal_unit_scale': 1.0,
    })
    doc.rootdict['ACAD_GEOGRAPHICDATA'] = geo_data

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.00002, dxfattribs={'layer': 'ODP_TIANG'})
            name = str(row.get('Name', ''))
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={'height': 0.00005}).set_placement((geom.x, geom.y))
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL'})

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dxf')
    doc.saveas(tmp.name)
    return tmp.name

# --- Tampilan Streamlit ---
st.title("📐 KML to DXF + Map Geolocation")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_all_layers(path)
        
        if not gdf.empty:
            st.sidebar.success(f"Ditemukan {len(gdf)} Jalur & Titik")
            
            # Tombol Download
            if st.sidebar.button("💾 Generate DXF Georeference"):
                dxf_file = convert_to_dxf_with_georef(gdf)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("Download DXF Sekarang", f, file_name="Map_Jaringan.dxf")

            # Preview Map di Streamlit
            st.subheader("📍 Preview Lokasi Jaringan")
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=18)
            # Menampilkan peta jalan & satelit
            folium.TileLayer('https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google Roads', name='Peta Jalan').add_to(m)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google Sat', name='Satelit').add_to(m)
            folium.LayerControl().add_to(m)
            
            # Gambar data ke peta
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'Point':
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='red').add_to(m)
                else:
                    folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
            folium_static(m, width=1000)
            
    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
