import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import tempfile
import os
import folium
import pandas as pd
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import unary_union

# --- 1. CONFIGURATION & LAYER PROPERTIES ---
st.set_page_config(page_title="KML to CAD Pro: Seamless Road Edition", layout="wide")

def get_layer_info(name):
    """Menentukan warna layer sesuai standar teknis gambar referensi."""
    name = str(name).upper()
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'TIANG_POLE', 2  # Kuning
    if any(k in name for k in ['ODC', 'ODP', 'BOX', 'FDT']):
        return 'DEVICE_RED', 1  # Merah
    if any(k in name for k in ['KABEL', 'FO', 'CABLE']):
        return 'CABLE_MAIN', 3  # Hijau
    return 'OBJEK_LAIN', 7 # Putih

# --- 2. CORE GEOSPATIAL PROCESSING ---
def load_and_project_kml(path):
    """Membaca KML dan memproyeksikan ke UTM (Meter) untuk akurasi tinggi."""
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
    
    # Proyeksi ke Meter agar lebar jalan tetap konsisten (misal 3.5m)
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_seamless(gdf_metric, original_gdf):
    """Membuat DXF dengan metode Seamless Road (Tanpa Garis Putus)."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers
    doc.layers.new(name='MAP_ROAD_OUTLINE', dxfattribs={'color': 7}) # Putih
    doc.layers.new(name='LABEL_INFO', dxfattribs={'color': 7})
    doc.layers.new(name='CABLE_OFFSET', dxfattribs={'color': 1})    # Merah

    # --- A. PROSES JALAN SEAMLESS (MENYAMBUNG TOTAL) ---
    avg_y, avg_x = original_gdf.geometry.centroid.y.mean(), original_gdf.geometry.centroid.x.mean()
    try:
        with st.spinner("Menyatukan jaringan jalan (Metode Seamless)..."):
            # Ambil data jalan dari OSM (dist 1km agar area luas tertangkap)
            streets = ox.graph_from_point((avg_y, avg_x), dist=1000, network_type='all', simplify=True)
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            
            # 1. Satukan semua garis jalan menjadi satu objek MultiLine (Merge Segments)
            all_lines = unary_union(edges_metric.geometry)
            
            # 2. Buat Buffer (Area Badan Jalan) sebesar 3.5 meter
            # cap_style=2 (flat) dan join_style=2 (mitre) agar sudut persimpangan rapi kotak
            road_polygon = all_lines.buffer(3.5, cap_style=2, join_style=2)
            
            # 3. Ambil Boundary (Garis Tepi) dari area tersebut
            # Boundary ini adalah garis luar yang mengelilingi seluruh jaringan jalan yang menyambung
            road_outline = road_polygon.boundary
            
            # Tambahkan ke CAD
            if isinstance(road_outline, (LineString, MultiLineString)):
                if hasattr(road_outline, 'geoms'): # Jika MultiLineString
                    for part in road_outline.geoms:
                        msp.add_lwpolyline(list(part.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
                else: # Jika LineString tunggal
                    msp.add_lwpolyline(list(road_outline.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
                    
    except Exception as e:
        st.sidebar.error(f"Error Pengolahan Jalan: {e}")

    # --- B. DATA KML (TIANG & KABEL) ---
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            # Gambar Lingkaran Tiang (TE)
            msp.add_circle((geom.x, geom.y), radius=0.6, dxfattribs={'layer': layer_name})
            # Label Nama Tiang
            msp.add_text(name, dxfattribs={'layer': 'LABEL_INFO', 'height': 1.0}).set_placement((geom.x + 0.8, geom.y + 0.8))
            
        elif geom.geom_type == 'LineString':
            # 1. Garis Utama Kabel (Hijau)
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color})
            
            # 2. Garis Parallel Offset Kabel (Garis Merah di samping Hijau)
            try:
                # Gunakan buffer boundary kecil untuk offset yang lebih stabil
                offset_c = geom.buffer(0.4, cap_style=2, join_style=2).boundary
                if hasattr(offset_c, 'geoms'):
                    for part in offset_c.geoms:
                        msp.add_lwpolyline(list(part.coords), dxfattribs={'layer': 'CABLE_OFFSET'})
                else:
                    msp.add_lwpolyline(list(offset_c.coords), dxfattribs={'layer': 'CABLE_OFFSET'})
            except: pass

            # 3. Label Angka Jarak
            mid = geom.interpolate(0.5, normalized=True)
            if row['Length_M'] > 0:
                msp.add_text(str(row['Length_M']), dxfattribs={'layer': 'LABEL_INFO', 'height': 0.9}).set_placement((mid.x + 0.5, mid.y + 0.5))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. STREAMLIT INTERFACE ---
st.title("📐 KML to DXF: Seamless Road & Cable Pro")
st.markdown("Solusi perbaikan: Semua persimpangan jalan disatukan menggunakan **Geospatial Union** agar tidak ada garis putus-putus.")

uploaded_file = st.sidebar.file_uploader("Upload KML File", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        st.sidebar.success(f"Berhasil memuat {len(gdf_metric)} objek.")
        
        if st.sidebar.button("🚀 Generate DXF Anti-Putus"):
            with st.spinner("Sedang menyambungkan jaringan jalan..."):
                orig_latlon = gdf_metric.to_crs(epsg=4326)
                dxf_file = generate_dxf_seamless(gdf_metric, orig_latlon)
                with open(dxf_file, "rb") as f:
                    st.sidebar.download_button("📥 Simpan File DXF", f, "Peta_Seamless_Pro.dxf")

        # Map Preview
        st.subheader("Satellite Preview")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satellite').add_to(m)
        folium_static(m, width=1000)
    
    os.unlink(path)
