import streamlit as st
import geopandas as gpd
import ezdxf
import folium
import plotly.graph_objects as go
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML to DXF - Stable", layout="wide")

def convert_kml_to_dxf(gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Layer setup
    doc.layers.new(name='GARIS', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='NODE', dxfattribs={'color': 1})  # Merah
    doc.layers.new(name='TEXT', dxfattribs={'color': 7})  # Putih

    for _, row in gdf.iterrows():
        geom = row.geometry
        # Validasi ganda: Pastikan hanya Point atau LineString
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'NODE'})
            name = str(row.get('Name', ''))
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={'layer': 'TEXT', 'height': 0.00008}).set_placement((geom.x, geom.y))
        
        elif geom.geom_type == 'LineString':
            coords = [(p[0], p[1]) for p in geom.coords]
            msp.add_lwpolyline(coords, dxfattribs={'layer': 'GARIS'})
    
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

st.title("📐 KML to DXF: Map & Schematic")

uploaded_file = st.sidebar.file_uploader("Upload file KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        # 1. Load data
        gdf_raw = gpd.read_file(path, driver='KML')
        
        # 2. FILTER KETAT: Hanya simpan Point dan LineString
        # Ini akan membuang Polygon sebelum masuk ke loop visualisasi
        gdf = gdf_raw[gdf_raw.geometry.type.isin(['Point', 'LineString'])].copy()

        if gdf.empty:
            st.warning("File KML tidak mengandung data Point atau LineString yang valid.")
        else:
            tab1, tab2 = st.tabs(["📍 Peta Lokasi", "📐 Skematik Jaringan"])

            with tab1:
                center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=18)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Satellite').add_to(m)
                
                for _, row in gdf.iterrows():
                    # Pengecekan eksplisit menggunakan geom_type string
                    if row.geometry.geom_type == 'Point':
                        folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                    elif row.geometry.geom_type == 'LineString':
                        # Hanya LineString yang memiliki atribut .coords
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

            if st.sidebar.button("💾 Download DXF"):
                dxf_file = convert_kml_to_dxf(gdf)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("Klik untuk Simpan", f, file_name="output_clean.dxf")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
    finally:
        if os.path.exists(path): os.unlink(path)
