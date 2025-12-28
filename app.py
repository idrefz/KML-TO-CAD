import streamlit as st
import geopandas as gpd
import ezdxf
import folium
import plotly.graph_objects as go
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML to DXF - Line & Point Only", layout="wide")

def convert_kml_to_dxf(gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Layer setup
    doc.layers.new(name='GARIS', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='NODE', dxfattribs={'color': 1})  # Merah
    doc.layers.new(name='TEXT', dxfattribs={'color': 7})  # Putih

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        # PROSES HANYA TITIK
        if isinstance(geom, Point):
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'NODE'})
            name = str(row.get('Name', ''))
            if name and name != 'None':
                msp.add_text(name, dxfattribs={'layer': 'TEXT', 'height': 0.00008}).set_placement((geom.x, geom.y))
        
        # PROSES HANYA GARIS (LineString)
        elif isinstance(geom, LineString):
            coords = [(p[0], p[1]) for p in geom.coords]
            msp.add_lwpolyline(coords, dxfattribs={'layer': 'GARIS'})
            
        # POLYGON DAN LAINNYA OTOMATIS DIABAIKAN (DI-SKIP)
    
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

st.title("📐 KML to DXF: Jaringan & Skematik")
st.markdown("Aplikasi ini hanya memproses **Titik (Nodes)** dan **Garis (Paths)**. Objek area (Polygon) akan diabaikan.")

uploaded_file = st.sidebar.file_uploader("Upload file KML Anda", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        # Load data menggunakan fiona engine
        gdf = gpd.read_file(path, driver='KML')
        
        # Filter hanya Point dan LineString untuk visualisasi agar tidak error
        gdf_filtered = gdf[gdf.geometry.type.isin(['Point', 'LineString'])]

        tab1, tab2 = st.tabs(["📍 Peta Satelit", "📐 Skematik CAD"])

        with tab1:
            if not gdf_filtered.empty:
                center = [gdf_filtered.geometry.centroid.y.mean(), gdf_filtered.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=18)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Satellite').add_to(m)
                
                for _, row in gdf_filtered.iterrows():
                    geom = row.geometry
                    if isinstance(geom, Point):
                        folium.CircleMarker([geom.y, geom.x], radius=4, color='red', fill=True).add_to(m)
                    elif isinstance(geom, LineString):
                        points = [[p[1], p[0]] for p in geom.coords]
                        folium.PolyLine(points, color='lime', weight=3).add_to(m)
                folium_static(m, width=1000)
            else:
                st.warning("Tidak ditemukan data Point atau LineString di file ini.")

        with tab2:
            fig = go.Figure()
            for _, row in gdf_filtered.iterrows():
                geom = row.geometry
                if isinstance(geom, LineString):
                    x, y = geom.xy
                    fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines+markers', 
                                             line=dict(color='lime', width=2), marker=dict(color='red', size=4)))
                elif isinstance(geom, Point):
                    fig.add_trace(go.Scatter(x=[geom.x], y=[geom.y], mode='markers+text', 
                                             text=[row.get('Name','')], textposition="top right",
                                             marker=dict(color='red', size=8)))

            fig.update_layout(
                plot_bgcolor='black', paper_bgcolor='black', font_color='white',
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x"),
                height=600, margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)

        if st.sidebar.button("💾 Download DXF"):
            dxf_file = convert_kml_to_dxf(gdf_filtered)
            with open(dxf_file, "rb") as f:
                st.sidebar.download_button("Klik untuk Simpan DXF", f, file_name="hasil_skematik.dxf")

    except Exception as e:
        st.error(f"Terjadi kesalahan saat membaca file: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)
