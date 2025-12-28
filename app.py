import streamlit as st
import geopandas as gpd
import ezdxf
import folium
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML Map & Schematic", layout="wide")

# Fungsi hitung jarak sederhana (pendekatan Euclidean untuk skematik)
def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5 * 111139 # Konversi kasar ke meter

def convert_kml_to_dxf(gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    doc.layers.new(name='GARIS', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='NODE', dxfattribs={'color': 1})  # Merah
    doc.layers.new(name='TEXT', dxfattribs={'color': 7})  # Putih

    for _, row in gdf.iterrows():
        geom = row.geometry
        if isinstance(geom, Point):
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': 'NODE'})
            msp.add_text(str(row.get('Name', '')), dxfattribs={'layer': 'TEXT', 'height': 0.00008}).set_placement((geom.x, geom.y))
        elif isinstance(geom, LineString):
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'GARIS'})
    
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- UI ---
st.title("🌐 KML Processor: Map & Schematic View")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf = gpd.read_file(path, driver='KML')
    
    # Membuat Tab
    tab1, tab2 = st.tabs(["📍 Peta Lokasi (Satelit)", "📐 Skematik Jaringan (CAD Style)"])

    with tab1:
        st.subheader("Geographic Location")
        center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=17, tiles=None)
        
        # Tambahkan Satelit Google
        folium.TileLayer(
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            attr='Google Satelit',
            name='Google Satellite',
            overlay=False,
            control=True
        ).add_to(m)
        
        # Plot data
        for _, row in gdf.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='red').add_to(m)
            else:
                points = [[p[1], p[0]] for p in row.geometry.coords]
                folium.PolyLine(points, color='lime', weight=2).add_to(m)
        
        folium_static(m, width=1000)

    with tab2:
        st.subheader("Schematic Diagram")
        st.info("Visualisasi garis dan node sesuai struktur file Anda (Background Hitam).")
        
        # Membuat visualisasi skematik sederhana dengan Plotly agar interaktif
        import plotly.graph_objects as go
        
        fig = go.Figure()

        for _, row in gdf.iterrows():
            if isinstance(row.geometry, LineString):
                x, y = row.geometry.xy
                fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines+markers', 
                                         line=dict(color='lime', width=2),
                                         marker=dict(color='red', size=6),
                                         name="Jalur"))
            elif isinstance(row.geometry, Point):
                fig.add_trace(go.Scatter(x=[row.geometry.x], y=[row.geometry.y], mode='text+markers',
                                         text=[row.get('Name', '')],
                                         textposition="top center",
                                         marker=dict(color='red', size=8),
                                         showlegend=False))

        fig.update_layout(
            plot_bgcolor='black',
            paper_bgcolor='black',
            font_color='white',
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x", scaleratio=1),
            margin=dict(l=0, r=0, t=0, b=0),
            height=600
        )
        st.plotly_chart(fig, use_container_width=True)

    # Download Button di Sidebar
    if st.sidebar.button("Generate & Download DXF"):
        dxf_file = convert_kml_to_dxf(gdf)
        with open(dxf_file, "rb") as f:
            st.sidebar.download_button("Click to Save DXF", f, file_name="output.dxf")
