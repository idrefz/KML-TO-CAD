import streamlit as st
import geopandas as gpd
import ezdxf
import folium
import plotly.graph_objects as go
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML to CAD - Fiber Network", layout="wide")

def convert_kml_to_dxf(gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Layer Setup sesuai jenis perangkat (ALPRO)
    doc.layers.new(name='KABEL_DISTRIBUSI', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='ODP_TITIK', dxfattribs={'color': 1})        # Merah
    doc.layers.new(name='TIANG_TE', dxfattribs={'color': 2})         # Kuning
    doc.layers.new(name='LABEL_NAME', dxfattribs={'color': 7})       # Putih

    for _, row in gdf.iterrows():
        geom = row.geometry
        name = str(row.get('Name', row.get('name', '')))
        
        if geom.geom_type == 'Point':
            # Bedakan layer berdasarkan nama atau folder
            layer = 'ODP_TITIK' if 'ODP' in name else 'TIANG_TE'
            msp.add_circle((geom.x, geom.y), radius=0.00003, dxfattribs={'layer': layer})
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={'layer': 'LABEL_NAME', 'height': 0.00008}).set_placement((geom.x, geom.y))
        
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL_DISTRIBUSI'})
    
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

st.title("🌐 Network Map & Schematic Viewer")
st.write("Menganalisis file KML: `" + "BNT,LBU,AI,kp karyautama cikedal" + "`")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

# Jika file tidak diupload manual, gunakan file yang baru saja Anda berikan
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name
    
    try:
        # Load & Filter hanya Point dan LineString (Mengabaikan Polygon/Boundry)
        gdf_raw = gpd.read_file(path, driver='KML')
        gdf = gdf_raw[gdf_raw.geometry.type.isin(['Point', 'LineString'])].copy()

        tab1, tab2 = st.tabs(["📍 Peta Lokasi Satelit", "📐 Skematik Jaringan (CAD Style)"])

        with tab1:
            st.subheader("Visualisasi Jalur Kabel & Alpro")
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=17)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
                            attr='Google', name='Google Satellite').add_to(m)
            
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'Point':
                    color = 'red' if 'ODP' in str(row.get('Name')) else 'yellow'
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=5, color=color, 
                                        popup=row.get('Name')).add_to(m)
                elif row.geometry.geom_type == 'LineString':
                    pts = [[p[1], p[0]] for p in row.geometry.coords]
                    folium.PolyLine(pts, color='lime', weight=4, tooltip=row.get('Name')).add_to(m)
            folium_static(m, width=1000)

        with tab2:
            st.subheader("Skematik Single Line Diagram")
            fig = go.Figure()
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'LineString':
                    x, y = row.geometry.xy
                    fig.add_trace(go.Scatter(x=list(x), y=list(y), mode='lines+markers', 
                                             line=dict(color='lime', width=2), marker=dict(color='white', size=2)))
                elif row.geometry.geom_type == 'Point':
                    fig.add_trace(go.Scatter(x=[row.geometry.x], y=[row.geometry.y], mode='markers+text', 
                                             text=[row.get('Name','')], textposition="top center",
                                             marker=dict(color='red', size=8)))

            fig.update_layout(plot_bgcolor='black', paper_bgcolor='black', font_color='white',
                             xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                             yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x"),
                             height=700)
            st.plotly_chart(fig, use_container_width=True)

        # Tombol Download
        if st.sidebar.button("💾 Export ke DXF (AutoCAD)"):
            dxf_file = convert_kml_to_dxf(gdf)
            with open(dxf_file, "rb") as f:
                st.sidebar.download_button("Download File DXF", f, file_name="Network_Output.dxf")

    except Exception as e:
        st.error(f"Gagal memproses: {e}")
