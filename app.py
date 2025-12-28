import streamlit as st
import geopandas as gpd
import ezdxf
import folium
from streamlit_folium import folium_static
import tempfile
import os
from shapely.geometry import Point, LineString

st.set_page_config(page_title="KML to DXF & Map Viewer", layout="wide")

st.title("🗺️ KML to DXF Converter & Viewer")

def convert_kml_to_dxf(gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Layer Setup
    doc.layers.new(name='GARIS_JARINGAN', dxfattribs={'color': 3}) # Hijau
    doc.layers.new(name='NODE_TITIK', dxfattribs={'color': 1})    # Merah
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7})    # Putih

    for _, row in gdf.iterrows():
        geom = row.geometry
        name = str(row['Name']) if 'Name' in gdf.columns else ""

        if isinstance(geom, Point):
            x, y = geom.x, geom.y
            msp.add_circle((x, y), radius=0.00005, dxfattribs={'layer': 'NODE_TITIK'})
            if name:
                msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 0.0001}).set_placement((x, y))

        elif isinstance(geom, LineString):
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'GARIS_JARINGAN'})

    temp_dxf = tempfile.NamedTemporaryFile(delete=False, suffix='.dxf')
    doc.saveas(temp_dxf.name)
    return temp_dxf.name

# --- SIDEBAR UPLOAD ---
st.sidebar.header("Upload File")
uploaded_file = st.sidebar.file_uploader("Pilih file KML", type=['kml'])

if uploaded_file is not None:
    # Simpan file sementara untuk dibaca geopandas
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        # Load Data
        gdf = gpd.read_file(tmp_path, driver='KML')
        
        # Layout kolom: Kiri Peta, Kanan Kontrol/Download
        col1, col2 = st.columns([3, 1])

        with col1:
            st.subheader("Preview Peta")
            # Inisialisasi Map (Centering ke data)
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=15, tiles='OpenStreetMap')
            
            # Tambahkan Tile Satelit sebagai opsi
            folium.TileLayer(
                tiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr = 'Esri',
                name = 'Satellite',
                overlay = False,
                control = True
            ).add_to(m)
            folium.LayerControl().add_to(m)

            # Gambar Geometri ke Peta
            for _, row in gdf.iterrows():
                sim_geo = row.geometry
                if isinstance(sim_geo, Point):
                    folium.CircleMarker(
                        location=[sim_geo.y, sim_geo.x],
                        radius=5,
                        color='red',
                        fill=True,
                        popup=row.get('Name', 'Point')
                    ).add_to(m)
                elif isinstance(sim_geo, LineString):
                    points = [[p[1], p[0]] for p in sim_geo.coords]
                    folium.PolyLine(points, color="green", weight=3, opacity=0.8).add_to(m)

            folium_static(m, width=800)

        with col2:
            st.subheader("Opsi Konversi")
            if st.button("Generate DXF"):
                dxf_path = convert_kml_to_dxf(gdf)
                with open(dxf_path, "rb") as f:
                    st.download_button(
                        label="💾 Download DXF",
                        data=f,
                        file_name=uploaded_file.name.replace(".kml", ".dxf"),
                        mime="application/dxf"
                    )
                os.unlink(dxf_path)

    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
else:
    st.info("Silakan upload file KML melalui sidebar untuk melihat preview.")
