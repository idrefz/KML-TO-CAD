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

# --- 1. KONFIGURASI LAYER & STYLE ---
st.set_page_config(page_title="KML to CAD Pro: Double-Line Road Edition", layout="wide")

def get_layer_info(name):
    """Menentukan warna dan nama layer berdasarkan kata kunci di KML."""
    name = str(name).upper()
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'POLE_TE', 2  # Kuning (Sesuai gambar referensi)
    if any(k in name for k in ['ODC', 'ODP', 'BOX']):
        return 'DEVICE_BOX', 1  # Merah
    if any(k in name for k in ['KABEL', 'FO', 'CABLE']):
        return 'CABLE_PATH', 3  # Hijau (Primary)
    return 'OBJEK_LAIN', 7 # Putih

# --- 2. FUNGSI PEMPROSESAN DATA ---
def load_and_project_kml(path):
    """Membaca KML dan memproyeksikan ke satuan METER (UTM) untuk akurasi offset."""
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
    full_gdf = full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    
    # Proyeksi otomatis ke UTM zona setempat (PENTING untuk hitungan Meter)
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    
    # Hitung panjang segmen untuk label angka di CAD
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_professional(gdf_metric, original_gdf):
    """Membuat DXF dengan jalan double-line dan kabel parallel offset."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Definisi Layer Dasar
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8}) # Abu-abu/Putih tipis
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7}) # Putih untuk angka/nama

    # --- BAGIAN A: PENGAMBILAN & PENEBALAN JALAN (OSM) ---
    avg_y, avg_x = original_gdf.geometry.centroid.y.mean(), original_gdf.geometry.centroid.x.mean()
    try:
        with st.spinner("Mengunduh data jalan dan membuat garis tepi..."):
            # Tarik data jalan dari OpenStreetMap
            streets = ox.graph_from_point((avg_y, avg_x), dist=800, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            
            for _, edge in edges_metric.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    # Membuat 2 garis tepi jalan (Double Line)
                    # Jarak 3.5m ke kiri dan 3.5m ke kanan (Total lebar jalan 7m)
                    try:
                        line_geom = edge.geometry
                        left_edge = line_geom.parallel_offset(3.5, 'left', join_style=2)
                        right_edge = line_geom.parallel_offset(3.5, 'right', join_style=2)
                        
                        if left_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(left_edge.coords), dxfattribs={'layer': 'MAP_JALAN'})
                        if right_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(right_edge.coords), dxfattribs={'layer': 'MAP_JALAN'})
                    except:
                        # Jika jalan terlalu pendek/rumit untuk offset, gunakan garis tunggal
                        msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"OSM Road Error: {e}")

    # --- BAGIAN B: PLOT DATA KML (KABEL, TIANG, LABEL) ---
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            # Gambar Lingkaran Tiang/Node (Radius 0.7m)
            msp.add_circle((geom.x, geom.y), radius=0.7, dxfattribs={'layer': layer_name})
            # Label Nama (TE, ODP, dll)
            if name.lower() != 'none':
                msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.1}).set_placement((geom.x + 1.2, geom.y + 1.2))
            
        elif geom.geom_type == 'LineString':
            # 1. Garis Utama Kabel (Warna Hijau standar)
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color})
            
            # 2. Garis Offset Kabel (Efek ganda Merah/Hijau sesuai contoh gambar)
            try:
                # Offset 0.5 meter ke samping kiri
                offset_kabel = geom.parallel_offset(0.5, 'left', join_style=2)
                if offset_kabel.geom_type == 'LineString':
                    msp.add_lwpolyline(list(offset_kabel.coords), dxfattribs={'layer': layer_name, 'color': 1}) # Merah
            except: pass

            # 3. Label Angka Jarak di Tengah Segmen (Sesuai contoh gambar)
            mid_point = geom.interpolate(0.5, normalized=True)
            msp.add_text(f"{row['Length_M']}", dxfattribs={
                'layer': 'LABEL_TEKS', 
                'height': 1.0
            }).set_placement((mid_point.x + 0.6, mid_point.y + 0.6))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. APLIKASI STREAMLIT ---
st.title("📐 Professional KML to CAD Converter")
st.markdown("Pembaruan: Visualisasi jalan raya otomatis menggunakan **Double-Line** dan kabel dengan **Parallel Offset**.")

uploaded_file = st.sidebar.file_uploader("Unggah File KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        st.sidebar.header("📊 Statistik Proyek")
        total_len = gdf_metric[gdf_metric.geometry.type == 'LineString']['Length_M'].sum()
        st.sidebar.metric("Total Panjang Kabel", f"{total_len:,.1f} m")
        
        if st.sidebar.button("🚀 Ekspor ke DXF Professional"):
            with st.spinner("Memproses peta dan jalan..."):
                orig_latlon = gdf_metric.to_crs(epsg=4326)
                dxf_file = generate_dxf_professional(gdf_metric, orig_latlon)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("📥 Klik untuk Unduh DXF", f, "Peta_DoubleLine_Pro.dxf")

        # Preview Peta (Fungsi Visual Saja)
        st.subheader("Pratinjau Satelit")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Google Hybrid').add_to(m)
        folium_static(m, width=1000)
    
    os.unlink(path)
