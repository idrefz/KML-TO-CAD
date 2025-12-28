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

# --- 1. CONFIGURATION & LAYER LOGIC ---
st.set_page_config(page_title="KML to CAD Pro (Parallel Line Edition)", layout="wide")

def get_layer_info(name):
    """Categorize objects to match the visual style of the reference image."""
    name = str(name).upper()
    # "TE" often refers to Pole/Tiang in your screenshot
    if any(k in name for k in ['TE', 'POLE', 'TIANG']):
        return 'POLE_TE', 2  # Yellow
    if any(k in name for k in ['ODC', 'ODP', 'BOX', 'FAT']):
        return 'DEVICE_BOX', 1  # Red
    if any(k in name for k in ['CABLE', 'KABEL', 'FO', 'DROP']):
        return 'CABLE_PATH', 3  # Green (Primary)
    return 'DEFAULT_LAYER', 7 # White

# --- 2. CORE PROCESSING ---
def load_and_project_kml(path):
    """Reads KML and converts to Metric (Meters) for accurate CAD offsets."""
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
    
    # Auto-detect UTM zone to work in METERS
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    
    # Calculate segment lengths
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 1) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf_pro(gdf_metric, original_gdf):
    """Creates DXF with Parallel Offset lines and Labels to match user screenshot."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Pre-define standard layers
    doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7})
    doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8}) # Grey for roads

    # 1. Background: OSM Streets
    avg_y, avg_x = original_gdf.geometry.centroid.y.mean(), original_gdf.geometry.centroid.x.mean()
    try:
        streets = ox.graph_from_point((avg_y, avg_x), dist=700, network_type='drive')
        _, edges = ox.graph_to_gdfs(streets)
        edges_metric = edges.to_crs(gdf_metric.crs)
        for _, edge in edges_metric.iterrows():
            if edge.geometry.geom_type == 'LineString':
                msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except: pass

    # 2. Design: KML Data
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            # Create a point circle (0.8m radius)
            msp.add_circle((geom.x, geom.y), radius=0.8, dxfattribs={'layer': layer_name})
            # Label (e.g., TE 19)
            msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.1}).set_placement((geom.x + 1.2, geom.y + 1.2))
            
        elif geom.geom_type == 'LineString':
            # MAIN LINE (The center path)
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name, 'color': color})
            
            # PARALLEL OFFSET (The "Double Line" effect from your image)
            try:
                # Offset 0.4 meters to the left
                left_line = geom.parallel_offset(0.4, 'left', join_style=2)
                if left_line.geom_type == 'LineString':
                    msp.add_lwpolyline(list(left_line.coords), dxfattribs={'layer': layer_name, 'color': 1}) # Red Line
            except: pass

            # DISTANCE LABEL (The number in the middle of the line segment)
            mid = geom.interpolate(0.5, normalized=True)
            if row['Length_M'] > 0:
                msp.add_text(f"{row['Length_M']}", dxfattribs={
                    'layer': 'LABEL_TEKS', 
                    'height': 1.0
                }).set_placement((mid.x + 0.6, mid.y + 0.6))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. STREAMLIT INTERFACE ---
st.title("📐 KML to CAD Pro: Parallel Line Mapping")
st.markdown("Generates DXF with **offset cable lines** and **automated labels** based on your reference image.")

uploaded_file = st.sidebar.file_uploader("Upload KML", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        # Dashboard Stats
        st.sidebar.header("📋 Project Stats")
        st.sidebar.metric("Total Cable", f"{gdf_metric['Length_M'].sum():,.1f} Meters")
        
        summary = gdf_metric.copy()
        summary['Layer'] = summary['Name'].apply(lambda x: get_layer_info(x)[0])
        st.sidebar.table(summary.groupby('Layer').size().rename("Qty"))

        if st.sidebar.button("🚀 Export Parallel DXF"):
            with st.spinner("Generating CAD file..."):
                original_gdf = gdf_metric.to_crs(epsg=4326)
                dxf_path = generate_dxf_pro(gdf_metric, original_gdf)
                with open(dxf_path, "rb") as f:
                    st.sidebar.download_button("📥 Download DXF Map", f, "Parallel_Map_Export.dxf")

        # Map Preview
        st.subheader("Satellite Preview")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=18)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Google Hybrid').add_to(m)
        
        for _, row in gdf_latlon.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='yellow', fill=True, tooltip=row['Name']).add_to(m)
            else:
                folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=4, opacity=0.8).add_to(m)
        
        folium_static(m, width=1000)
    
    os.unlink(path)
