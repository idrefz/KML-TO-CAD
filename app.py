import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import tempfile
import os
import pandas as pd
from shapely.geometry import Point, LineString, MultiLineString

# --- 1. CONFIGURATION & LAYER PROPERTIES ---
st.set_page_config(page_title="KML to CAD Pro: Fixed Road Geometry", layout="wide")

def get_layer_info(name):
    name = str(name).upper()
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'TIANG_POLE', 2  # Kuning
    if any(k in name for k in ['ODC', 'ODP', 'BOX', 'FDT']):
        return 'DEVICE_RED', 1  # Merah
    if any(k in name for k in ['KABEL', 'FO', 'CABLE']):
        return 'CABLE_MAIN', 3  # Hijau
    return 'OBJEK_LAIN', 7 # Putih

# --- 2. FUNGSI PERBAIKAN GEOMETRI ---
def safe_parallel_offset(geom, distance, side):
    """
    Fungsi offset yang lebih stabil. Jika parallel_offset gagal/putus, 
    menggunakan metode buffer boundary sebagai cadangan.
    """
    try:
        # Coba parallel_offset standar dulu
        offset_line = geom.parallel_offset(distance, side, join_style=2, mitre_limit=5.0)
        return offset_line
    except:
        # Jika gagal, gunakan buffer lalu ambil garis tepinya (boundary)
        # Ini mencegah garis putus-putus pada tikungan tajam
        buff = geom.buffer(distance, cap_style=2, join_style=2)
        return buff.boundary

# --- 3. CORE PROCESSING ---
def load_and_project_kml(path):
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
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_fixed(gdf_metric, original_gdf):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers
    doc.layers.new(name='MAP_ROAD_OUTLINE', dxfattribs={'color': 7})
    doc.layers.new(name='LABEL_INFO', dxfattribs={'color': 7})
    doc.layers.new(name='CABLE_OFFSET', dxfattribs={'color': 1})

    # --- A. DETILING JALAN (DENGAN FIX GARIS PUTUS) ---
    avg_y, avg_x = original_gdf.geometry.centroid.y.mean(), original_gdf.geometry.centroid.x.mean()
    try:
        with st.spinner("Memproses geometri jalan anti-putus..."):
            # Gunakan dist lebih besar agar coverage luas
            streets = ox.graph_from_point((avg_y, avg_x), dist=1000, network_type='all', simplify=True)
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            
            for _, edge in edges_metric.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    # Lebar jalan 3.5m kiri & kanan
                    for side in ['left', 'right']:
                        offset_line = safe_parallel_offset(edge.geometry, 3.5, side)
                        
                        # Handle jika hasil offset berupa MultiLineString agar tidak error saat diplot
                        if isinstance(offset_line, MultiLineString):
                            for part in offset_line.geoms:
                                msp.add_lwpolyline(list(part.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
                        elif hasattr(offset_line, 'coords'):
                            msp.add_lwpolyline(list(offset_line.coords), dxfattribs={'layer': 'MAP_ROAD_OUTLINE'})
    except Exception as e:
        st.sidebar.error(f"Gagal memproses jalan: {e}")

    # --- B. DETILING KML ---
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=0.6, dxfattribs={'layer': layer_name})
            msp.add_text(name, dxfattribs={'layer': 'LABEL_INFO', 'height': 1.0}).set_placement((geom.x + 0.8, geom.y + 0.8))
            
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color})
            
            # Offset kabel juga menggunakan fungsi safe_parallel_offset
            try:
                offset_c = safe_parallel_offset(geom, 0.4, 'left')
                if hasattr(offset_c, 'coords'):
                    msp.add_lwpolyline(list(offset_c.coords), dxfattribs={'layer': 'CABLE_OFFSET'})
            except: pass

            mid = geom.interpolate(0.5, normalized=True)
            if row['Length_M'] > 0:
                msp.add_text(str(row['Length_M']), dxfattribs={'layer': 'LABEL_INFO', 'height': 0.9}).set_placement((mid.x + 0.5, mid.y + 0.5))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. STREAMLIT UI ---
st.title("📐 KML to DXF: High-Detail Road (Fixed Geometry)")
st.markdown("Pembaruan: Menggunakan metode **Safe Offset** untuk mencegah garis jalan putus-putus pada tikungan tajam.")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        if st.sidebar.button("🚀 Ekspor DXF Anti-Putus"):
            orig_latlon = gdf_metric.to_crs(epsg=4326)
            dxf_file = generate_dxf_fixed(gdf_metric, original_latlon=orig_latlon)
            with open(dxf_file, "rb") as f:
                st.sidebar.download_button("📥 Simpan DXF", f, "Peta_Rapi_Fixed.dxf")

        st.subheader("Map Preview")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium_static(m, width=1000)
    
    os.unlink(path)
