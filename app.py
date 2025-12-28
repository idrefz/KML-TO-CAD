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

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="KML to CAD Pro: Ultimate", layout="wide")

def get_layer_info(name):
    """Logic to categorize objects by keyword and assign CAD colors."""
    name = str(name).upper()
    if any(k in name for k in ['POLE', 'TIANG']):
        return 'TIANG_PLN', 1  # Red
    if any(k in name for k in ['ODP', 'BOX', 'FAT', 'ONT']):
        return 'PERANGKAT_TITIK', 2 # Yellow
    if any(k in name for k in ['CABLE', 'KABEL', 'FO', 'DROP']):
        return 'KABEL_JARINGAN', 3 # Green
    return 'LAIN_LAIN', 7 # White

# --- 2. CORE PROCESSING FUNCTIONS ---
def load_and_project_kml(path):
    """Reads KML and projects to UTM (meters)."""
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
    # Filter only relevant geometry
    full_gdf = full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    
    # Estimate UTM CRS for metric units (Meters)
    utm_gdf = full_gdf.to_crs(full_gdf.estimate_utm_crs())
    
    # Calculate lengths for lines
    utm_gdf['Length_M'] = utm_gdf.apply(
        lambda row: round(row.geometry.length, 2) if row.geometry.geom_type == 'LineString' else 0, axis=1
    )
    return utm_gdf

def generate_dxf(gdf_metric, original_gdf):
    """Creates a georeferenced DXF with layers and labels."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Create required layers
    layers = {'LABEL_TEKS': 7, 'MAP_JALAN': 8}
    for name, color in layers.items():
        doc.layers.new(name=name, dxfattribs={'color': color})

    # 1. Add OSM Street Data (Background)
    avg_y = original_gdf.geometry.centroid.y.mean()
    avg_x = original_gdf.geometry.centroid.x.mean()
    try:
        with st.spinner("Fetching OSM street vectors..."):
            streets = ox.graph_from_point((avg_y, avg_x), dist=600, network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            edges_metric = edges.to_crs(gdf_metric.crs)
            for _, edge in edges_metric.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except: st.sidebar.warning("OSM Streets skipped.")

    # 2. Add KML Data
    for _, row in gdf_metric.iterrows():
        geom = row.geometry
        name = str(row.get('Name', 'Unnamed'))
        layer_name, color = get_layer_info(name)
        
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})

        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=1.0, dxfattribs={'layer': layer_name})
            msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.2}).set_placement((geom.x + 1, geom.y + 1))
            
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': layer_name})
            # Add length label at midpoint
            mid = geom.interpolate(0.5, normalized=True)
            msp.add_text(f"{row['Length_M']}m", dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.0}).set_placement((mid.x, mid.y))

    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- 3. STREAMLIT UI ---
st.title("📐 Professional KML to CAD Converter")
st.info("Uploaded KMLs are automatically converted to **Metric (Meters)** and categorized by layer.")

uploaded_file = st.sidebar.file_uploader("Upload KML File", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    gdf_metric = load_and_project_kml(path)
    
    if gdf_metric is not None:
        # --- Sidebar Stats ---
        st.sidebar.header("📊 Inventory Data")
        total_len = gdf_metric['Length_M'].sum()
        st.sidebar.metric("Total Cable Length", f"{total_len:,.2f} m")
        
        summary = gdf_metric.copy()
        summary['Layer'] = summary['Name'].apply(lambda x: get_layer_info(x)[0])
        st.sidebar.write(summary.groupby('Layer').size().rename("Count"))

        # --- Action Buttons ---
        if st.sidebar.button("🚀 Generate DXF"):
            # We pass the original lat/lon gdf for the OSM center point
            original_gdf = gdf_metric.to_crs(epsg=4326)
            dxf_path = generate_dxf(gdf_metric, original_gdf)
            with open(dxf_path, "rb") as f:
                st.sidebar.download_button("📥 Download DXF", f, "Project_Layout.dxf")

        csv_data = gdf_metric.drop(columns='geometry').to_csv(index=False).encode('utf-8')
        st.sidebar.download_button("📝 Download CSV Report", csv_data, "Inventory.csv")

        # --- Visual Map ---
        st.subheader("Map Preview")
        gdf_latlon = gdf_metric.to_crs(epsg=4326)
        center = [gdf_latlon.geometry.centroid.y.mean(), gdf_latlon.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=17)
        folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satellite').add_to(m)
        
        for _, row in gdf_latlon.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='red', tooltip=row['Name']).add_to(m)
            else:
                folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3, tooltip=f"{row['Length_M']}m").add_to(m)
        folium_static(m, width=1000)
    
    os.unlink(path)
