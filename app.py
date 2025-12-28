import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import folium
from streamlit_folium import folium_static
import tempfile
import os
import pandas as pd
from shapely.geometry import Point, LineString

# --- 1. KONFIGURASI HALAMAN & STYLE ---
st.set_page_config(page_title="KML to CAD Pro: Ultimate Road & Cable", layout="wide")

def get_layer_info(name):
    """Kategorisasi layer berdasarkan keyword nama objek di KML."""
    name = str(name).upper()
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'POLE_TE', 2  # Kuning (Yellow)
    if any(k in name for k in ['ODC', 'ODP', 'BOX', 'FAT']):
        return 'DEVICE_BOX', 1  # Merah (Red)
    if any(k in name for k in ['KABEL', 'FO', 'CABLE', 'DROP']):
        return 'CABLE_MAIN', 3  # Hijau (Green)
    return 'DEFAULT_LAYER', 7 # Putih (White)

# --- 2. FUNGSI PEMPROSESAN GEOSPASIAL ---
def load_and_project_kml(path):
    """Membaca KML dan memproyeksikan ke satuan METER (UTM)."""
    layers = fiona.listlayers(path)
    gdfs = []
    for layer in layers:
        try:
            tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
            if not tmp_gdf.empty:
                gdfs.append(tmp_gdf)
        except: continue
    
    if not gdfs: return None
    
    full_gdf = pd.concat(gdfs, ignore_index=True)
    # Filter hanya Point dan LineString
    full_gdf = full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    
    # Deteksi otomatis zona UTM terbaik untuk lokasi data (satuan Meter)
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    
    # Hitung panjang segmen dalam meter
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_professional(gdf_metric, original_gdf):
    """Membuat DXF dengan jalan double-line dan kabel parallel offset."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layer Dasar
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8}) # Abu-abu
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7}) # Putih

    # --- PERBAIKAN: DOWNLOAD & TEBALKAN JALAN (ROAD MAPS) ---
    avg_y, avg_x = original_gdf.geometry.centroid.y.mean(), original_gdf.geometry.centroid.x.mean()
    try:
        with st.spinner("Mengunduh dan menebalkan vektor jalan..."):
            # Ambil data jaringan jalan dari OSM
            streets = ox.graph_from_point((avg_y, avg_x), dist=800, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            
            for _, edge in edges_metric.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    # Membuat visualisasi jalan dengan dua garis tepi (Double Line)
                    # Jarak 3.5m ke kiri dan 3.5m ke kanan (Lebar jalan standar 7m)
                    try:
                        line_geom = edge.geometry
                        left_edge = line_geom.parallel_offset(3.5, 'left', join_style=2)
                        right_edge = line_geom.parallel_offset(3.5, 'right', join_style=2)
                        
                        if left_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(left_edge.coords), dxfattribs={'layer': 'MAP_JALAN'})
                        if right_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(right_edge.coords), dxfattribs={'layer': 'MAP_JALAN'})
                    except:
                        # Fallback jika offset gagal: gunakan garis tunggal tipis
                        msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"OSM Road Error: {e}")

    # --- PERBAIKAN: PLOT KABEL & TIANG (KML DATA) ---
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            # Gambar Lingkaran Tiang (Radius 0.8 meter)
            msp.add_circle((geom.x, geom.y), radius=0.8, dxfattribs={'layer': layer_name})
            # Label Nama (contoh: TE 19)
            msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.1}).set_placement((geom.x + 1.2, geom.y + 1.2))
            
        elif geom.geom_type == 'LineString':
            # 1. Garis Utama (Hijau/Sesuai Layer)
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color, 'const_width': 0.1})
            
            # 2. Parallel Offset (Efek kabel ganda Red/Green seperti di gambar referensi)
            try:
                # Offset 0.4 meter ke kiri (Garis Merah)
                offset_geom = geom.parallel_offset(0.4, 'left', join_style=2)
                if offset_geom.geom_type == 'LineString':
                    msp.add_lwpolyline(list(offset_geom.coords), dxfattribs={'layer': layer_name, 'color': 1}) # Warna Merah
            except: pass

            # 3. Label Angka Jarak (Hanya angka sesuai gambar)
            if row['Length_M'] > 0:
                mid = geom.interpolate(0.5, normalized=True)
                msp.add_text(f"{row['Length_M']}", dxfattribs={
                    'layer': 'LABEL_TEKS', 
                    'height': 1.0
                }).set_placement((mid.x + 0.6, mid.y + 0.6))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. ANTARMUKA STREAMLIT ---
st.title("📐 Professional KML to CAD Converter")
st.markdown("""
Fitur Utama:
- **Jalan Double-Line**: Jalan OSM ditarik sebagai dua garis tepi (tebal).
- **Kabel Parallel**: Efek garis ganda (Merah-Hijau) otomatis.
- **Auto-Label**: Menampilkan angka jarak dan nama tiang (TE).
""")

uploaded_file = st.sidebar.file_uploader("Upload File KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        # Statistik di Sidebar
        st.sidebar.header("📊 Ringkasan Data")
        total_kabel = gdf_metric[gdf_metric.geometry.type == 'LineString']['Length_M'].sum()
        st.sidebar.metric("Total Panjang Kabel", f"{total_kabel:,.1f} m")
        
        # Tombol Ekspor
        if st.sidebar.button("🚀 Generate DXF Professional"):
            with st.spinner("Memproses file CAD..."):
                original_latlon = gdf_metric.to_crs(epsg=4326)
                dxf_out = generate_dxf_professional(gdf_metric, original_latlon)
                with open(dxf_out, "rb") as f:
                    st.sidebar.download_button("📥 Download DXF", f, "Peta_Teknis_Pro.dxf")

        # Visualisasi Preview
        st.subheader("Preview Peta Satelit")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satellite').add_to(m)
        
        for _, row in gdf_latlon.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='yellow', fill=True).add_to(m)
            else:
                folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
        folium_static(m, width=1000)
    
    os.unlink(path)
