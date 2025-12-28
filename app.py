import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import folium
import tempfile
import os
from streamlit_folium import folium_static
from shapely.ops import transform

# Set Page Config
st.set_page_config(page_title="KML to CAD Pro v2", layout="wide")

def load_kml_properly(path):
    """Reads all KML layers and returns a GeoDataFrame in WGS84."""
    layers = fiona.listlayers(path)
    gdfs = []
    for layer in layers:
        try:
            tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
            if not tmp_gdf.empty:
                gdfs.append(tmp_gdf)
        except:
            continue
    if gdfs:
        full_gdf = gpd.pd.concat(gdfs, ignore_index=True)
        # Filter only Point and LineString
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_final(gdf_wgs84):
    """
    Converts WGS84 GDF to a Projected DXF (UTM).
    This ensures 1 unit in CAD = 1 Meter.
    """
    # 1. Project to UTM automatically based on centroid
    utm_gdf = gdf_wgs84.estimate_utm_crs()
    gdf_projected = gdf_wgs84.to_crs(utm_gdf)
    
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Setup Layers with Standard CAD Colors
    layers = {
        'MAP_JALAN': 8,       # Grey
        'KABEL_JARINGAN': 3,  # Green
        'PERANGKAT_TITIK': 1, # Red
        'LABEL_TEKS': 7       # White/Black
    }
    for name, color in layers.items():
        doc.layers.new(name=name, dxfattribs={'color': color})

    # 2. Fetch OSM Roads using Bounding Box (More robust than Point)
    try:
        with st.spinner("Fetching road vectors..."):
            bounds = gdf_wgs84.total_bounds # [minx, miny, maxx, maxy]
            # Buffer the bounds slightly
            streets = ox.graph_from_bbox(bounds[3]+0.002, bounds[1]-0.002, 
                                        bounds[2]+0.002, bounds[0]-0.002, 
                                        network_type='drive')
            _, edges = ox.graph_to_gdfs(streets)
            edges_projected = edges.to_crs(utm_gdf)
            
            for _, edge in edges_projected.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': 'MAP_JALAN'})
    except Exception as e:
        st.sidebar.warning(f"OSM Roads skipped: {e}")

    # 3. Plot KML Data in Meters
    for _, row in gdf_projected.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        
        if geom.geom_type == 'Point':
            # In UTM, radius is in meters. 0.5 = 50cm circle
            msp.add_circle((geom.x, geom.y), radius=0.5, dxfattribs={'layer': 'PERANGKAT_TITIK'})
            if name and name.lower() != 'none':
                # Text height 1.5 meters for readability
                msp.add_text(name, dxfattribs={'layer': 'LABEL_TEKS', 'height': 1.2}).set_placement((geom.x + 1, geom.y + 1))
        
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': 'KABEL_JARINGAN'})
            
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- UI ---
st.title("📐 Professional KML to DXF Converter")
st.info("This version automatically converts coordinates to **Meters (UTM)** for accurate CAD scaling.")

uploaded_file = st.sidebar.file_uploader("Upload KML File", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)
        
        if not gdf.empty:
            col1, col2 = st.columns([1, 3])
            
            with col1:
                st.metric("Total Objects", len(gdf))
                if st.button("🚀 Generate DXF (Meters)"):
                    dxf_path = convert_to_dxf_final(gdf)
                    with open(dxf_path, "rb") as f:
                        st.download_button("📥 Download DXF", f, "Project_Meters.dxf", "application/dxf")
            
            with col2:
                # Preview Map
                center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=16)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', 
                                attr='Google', name='Google Hybrid').add_to(m)
                
                for _, row in gdf.iterrows():
                    if row.geometry.geom_type == 'Point':
                        folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='red').add_to(m)
                    else:
                        folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=2).add_to(m)
                folium_static(m, width=800)
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        if os.path.exists(path): os.unlink(path)
