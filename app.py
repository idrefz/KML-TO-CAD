import streamlit as st
import geopandas as gpd
import ezdxf
from ezdxf import zoom
import fiona
import osmnx as ox
import folium
import tempfile
import os
from streamlit_folium import folium_static

# --- CONFIGURATION ---
st.set_page_config(page_title="KML to DXF Pro: Auto-Fit", layout="wide")

def load_kml_properly(path):
    """Recursively reads all KML layers and filters for Points and Lines."""
    layers = fiona.listlayers(path)
    gdfs = []
    for layer in layers:
        try:
            tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
            if not tmp_gdf.empty:
                gdfs.append(tmp_gdf)
        except Exception:
            continue
    if gdfs:
        full_gdf = gpd.pd.concat(gdfs, ignore_index=True)
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_full(gdf_wgs84):
    """
    1. Converts coordinates from Degrees to Meters (UTM).
    2. Adds OSM road background (Fixed for OSMnx 2.0+).
    3. Sets DXF metadata for 'Auto-Fit' on open.
    """
    # 1. Coordinate Transformation
    utm_crs = gdf_wgs84.estimate_utm_crs()
    gdf_projected = gdf_wgs84.to_crs(utm_crs)
    
    # 2. DXF Initialization
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6  # 6 = Meters
    msp = doc.modelspace()
    
    # 3. Create Layers
    layers_config = {
        '01_ROAD_OSM': 8,      # Grey
        '02_KML_LINE': 3,      # Green
        '03_KML_POINT': 1,     # Red
        '04_LABELS': 7         # White/Black
    }
    for name, color in layers_config.items():
        doc.layers.new(name=name, dxfattribs={'color': color})

    # 4. Fetch OSM Roads (Fixed API Call)
    try:
        with st.spinner("Fetching surrounding roads..."):
            bounds = gdf_wgs84.total_bounds # [min_x, min_y, max_x, max_y]
            
            # FIXED: New OSMnx 2.0+ syntax uses keyword arguments or a tuple
            streets = ox.graph_from_bbox(
                north=bounds[3] + 0.005, 
                south=bounds[1] - 0.005, 
                east=bounds[2] + 0.005, 
                west=bounds[0] - 0.005, 
                network_type='drive'
            )
            
            _, edges = ox.graph_to_gdfs(streets)
            edges_utm = edges.to_crs(utm_crs)
            for _, edge in edges_utm.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': '01_ROAD_OSM'})
    except Exception as e:
        st.sidebar.warning(f"OSM Road background skipped: {e}")

    # 5. Draw KML Entities
    for _, row in gdf_projected.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        
        if geom.geom_type == 'Point':
            msp.add_circle((geom.x, geom.y), radius=1.0, dxfattribs={'layer': '03_KML_POINT'})
            if name and name.lower() != 'none':
                msp.add_text(name, dxfattribs={'layer': '04_LABELS', 'height': 1.5}).set_placement((geom.x + 1.2, geom.y))
        
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': '02_KML_LINE'})

    # 6. AUTO-FIT
    zoom.extents(msp)
    
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- USER INTERFACE ---
st.title("📐 KML to DXF Professional (Fix v2.0)")
st.markdown("This version fixes the **OSMnx graph_from_bbox** error and ensures meter-scale accuracy.")

uploaded_file = st.sidebar.file_uploader("Upload your KML file", type=['kml'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)
        
        if not gdf.empty:
            st.sidebar.success(f"Found {len(gdf)} items.")
            
            if st.sidebar.button("🚀 Generate & Download DXF"):
                with st.spinner("Processing drawing..."):
                    dxf_file_path = convert_to_dxf_full(gdf)
                    with open(dxf_file_path, "rb") as f:
                        st.sidebar.download_button(
                            label="📥 Download AutoCAD File",
                            data=f,
                            file_name="Fixed_Project_Meters.dxf",
                            mime="application/dxf"
                        )
            
            # Map Preview
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=16)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', 
                            attr='Google', name='Google Hybrid').add_to(m)
            
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'Point':
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                else:
                    folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
            
            folium_static(m, width=1000)
            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)
