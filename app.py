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

# --- 1. KONFIGURASI LAYER & LOGIKA KATEGORISASI ---
st.set_page_config(page_title="KML to CAD Pro: High-Detail Road & Cable", layout="wide")

def get_layer_info(name):
    """Menentukan layer dan warna berdasarkan standar gambar teknis."""
    name = str(name).upper()
    # Kategori Tiang (TE)
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'TIANG_POLE', 2  # Kuning (Yellow)
    # Kategori Perangkat (ODP/ODC)
    if any(k in name for k in ['ODC', 'ODP', 'BOX', 'FDT', 'FAT']):
        return 'DEVICE_RED', 1  # Merah (Red)
    # Kategori Kabel
    if any(k in name for k in ['KABEL', 'FO', 'CABLE', 'DROP']):
        return 'CABLE_MAIN', 3  # Hijau (Green)
    return 'OBJEK_LAIN', 7 # Putih (White)

# --- 2. FUNGSI PEMPROSESAN DATA ---
def load_and_project_kml(path):
    """Membaca KML dan memproyeksikan ke satuan Meter (UTM) untuk akurasi CAD."""
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
    # Ambil hanya Point dan LineString (Abaikan Polygon)
    full_gdf = full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    
    # Proyeksi ke Meter agar perhitungan lebar jalan (3.5m) presisi
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    
    # Hitung panjang segmen kabel
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_high_detail(gdf_metric, original_gdf):
    """Membuat file DXF dengan detail jalan double-line dan label presisi."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Inisialisasi Layer Standar
    doc.layers.new(name='MAP_ROAD_OUTLINE', dxfattribs={'color': 7}) # Putih (Tepi Jalan)
    doc.layers.new(name='LABEL_INFO', dxfattribs={'color': 7})      # Putih (Teks)
    doc.layers.new(name='CABLE_OFFSET', dxfattribs={'color': 1})    # Merah (Bayangan Kabel)

    # --- A. DETILING JALAN (DOUBLE LINE & ROUNDABOUT) ---
    avg_y = original_gdf.geometry.centroid.y.mean()
    avg_x = original_gdf.geometry.centroid.x.mean()
    
    try:
        with st.spinner("Mengunduh geometri jalan (Roundabout & Junction)..."):
            # Mengambil data jalan raya (termasuk bundaran/roundabout)
            streets = ox.graph_from_point((avg_y, avg_x), dist=800, network_type='all', simplify=True)
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            
            for _, edge in edges_metric.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    try:
                        line = edge.geometry
                        # Membuat dua garis tepi jalan (lebar total 7 meter)
                        # join_style=2 (mitre) untuk sudut jalan yang tajam/rapi
                        left_edge = line.parallel_offset(3.5, 'left', join_style=2, mitre_limit=2.0)
                        right_edge = line.parallel_offset(3.5, 'right', join_style=2, mitre_limit=2.0)
                        
                        if left_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(left_edge.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
                        if right_edge.geom_type == 'LineString':
                            msp.add_lwpolyline(list(right_edge.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
                    except:
                        # Fallback: jika offset gagal, gunakan centerline asli
                        msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
    except Exception as e:
        st.sidebar.warning(f"OSM Road Error: {e}")

    # --- B. DETILING DATA KML (KABEL & TIANG) ---
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            # Gambar Lingkaran Tiang (TE) - Radius 0.6 meter
            msp.add_circle((geom.x, geom.y), radius=0.6, dxfattribs={'layer': layer_name})
            
            # Label Nama Tiang (TE 19, dsb) - Diberi offset agar tidak menumpuk lingkaran
            if name.lower() != 'none' and name != '':
                msp.add_text(name, dxfattribs={
                    'layer': 'LABEL_INFO', 
                    'height': 1.0
                }).set_placement((geom.x + 0.8, geom.y + 0.8))
            
        elif geom.geom_type == 'LineString':
            # 1. Garis Utama Kabel (Hijau)
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color})
            
            # 2. Garis Offset Kabel (Efek Kabel Ganda Merah/Hijau)
            try:
                # Offset kecil (0.4m) untuk garis bayangan merah
                offset_geom = geom.parallel_offset(0.4, 'left', join_style=2)
                if offset_geom.geom_type == 'LineString':
                    msp.add_lwpolyline(list(offset_geom.coords), dxfattribs={'layer': 'CABLE_OFFSET'})
            except: pass

            # 3. Label Angka Panjang Kabel (Hanya angka di tengah segmen)
            if row['Length_M'] > 0:
                mid_point = geom.interpolate(0.5, normalized=True)
                msp.add_text(str(row['Length_M']), dxfattribs={
                    'layer': 'LABEL_INFO', 
                    'height': 0.9
                }).set_placement((mid_point.x + 0.5, mid_point.y + 0.5))

    # Simpan ke file sementara
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. ANTARMUKA STREAMLIT (UI) ---
st.title("📐 KML to DXF High-Detail: Road & Fiber Mapping")
st.markdown("Menghasilkan detail **Double-Line Road** yang rapi, Bundaran, dan Label Teknis sesuai standar CAD.")

uploaded_file = st.sidebar.file_uploader("Unggah File KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        # Tampilkan Statistik di Sidebar
        st.sidebar.header("📊 Statistik Data")
        total_kabel = gdf_metric[gdf_metric.geometry.type == 'LineString']['Length_M'].sum()
        st.sidebar.metric("Total Panjang Kabel", f"{total_kabel:,.1f} m")
        
        # Tombol Ekspor
        if st.sidebar.button("🚀 Generate DXF Professional"):
            with st.spinner("Sedang merapikan geometri dan label..."):
                original_latlon = gdf_metric.to_crs(epsg=4326)
                dxf_file = generate_dxf_high_detail(gdf_metric, original_latlon)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("📥 Simpan File DXF", f, "Peta_Teknis_HighDetail.dxf")

        # Pratinjau Peta Satelit
        st.subheader("Satellite Preview")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satellite').add_to(m)
        
        # Tambahkan visualisasi kabel hijau di preview
        for _, row in gdf_latlon.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='yellow', fill=True).add_to(m)
            else:
                folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
        
        folium_static(m, width=1000)
    
    os.unlink(path)
