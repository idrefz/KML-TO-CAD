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
        # Filter: Ignore Polygons to keep the CAD file clean
        return full_gdf[full_gdf.geometry.type.isin(['Point', 'LineString'])]
    return gpd.GeoDataFrame()

def convert_to_dxf_full(gdf_wgs84):
    """
    1. Converts coordinates from Degrees to Meters (UTM).
    2. Adds OSM road background.
    3. Sets DXF metadata for 'Auto-Fit' on open.
    """
    # 1. Coordinate Transformation
    # Automatically finds the correct UTM zone (e.g., UTM 48S for Jakarta/Java)
    utm_crs = gdf_wgs84.estimate_utm_crs()
    gdf_projected = gdf_wgs84.to_crs(utm_crs)
    
    # 2. DXF Initialization (R2010 for high compatibility)
    doc = ezdxf.new('R2010')
    
    # CRITICAL: Set units to Meters (value 6) so AutoCAD doesn't treat it as mm
    doc.header['$INSUNITS'] = 6 
    
    msp = doc.modelspace()
    
    # 3. Create Layers with Standard Colors
    layers_config = {
        '01_ROAD_OSM': 8,      # Grey
        '02_KML_LINE': 3,      # Green
        '03_KML_POINT': 1,     # Red
        '04_LABELS': 7         # White/Black
    }
    for name, color in layers_config.items():
        doc.layers.new(name=name, dxfattribs={'color': color})

    # 4. Fetch OSM Roads (Background)
    try:
        with st.spinner("Fetching surrounding roads..."):
            bounds = gdf_wgs84.total_bounds # [min_x, min_y, max_x, max_y]
            # Fetch roads within a small buffer of the KML area
            streets = ox.graph_from_bbox(
                bounds[3]+0.005, bounds[1]-0.005, 
                bounds[2]+0.005, bounds[0]-0.005, 
                network_type='drive'
            )
            _, edges = ox.graph_to_gdfs(streets)
            edges_utm = edges.to_crs(utm_crs)
            for _, edge in edges_utm.iterrows():
                if edge.geometry.geom_type == 'LineString':
                    msp.add_lwpolyline(list(edge.geometry.coords), dxfattribs={'layer': '01_ROAD_OSM'})
    except Exception as e:
        st.sidebar.warning(f"OSM Road background skipped: {e}")

    # 5. Draw KML Entities (Projected in Meters)
    for _, row in gdf_projected.iterrows():
        geom = row.geometry
        name = str(row.get('Name', ''))
        
        if geom.geom_type == 'Point':
            # Drawing a 1-meter radius circle
            msp.add_circle((geom.x, geom.y), radius=1.0, dxfattribs={'layer': '03_KML_POINT'})
            if name and name.lower() != 'none':
                # Text height of 1.5 meters for clear visibility
                msp.add_text(name, dxfattribs={'layer': '04_LABELS', 'height': 1.5}).set_placement((geom.x + 1.2, geom.y))
        
        elif geom.geom_type == 'LineString':
            msp.add_lwpolyline(list(geom.coords), dxfattribs={'layer': '02_KML_LINE'})

    # 6. AUTO-FIT: Calculate extents and set the camera
    zoom.extents(msp)
    
    # Save to a temporary file
    tmp_path = tempfile.mktemp(suffix='.dxf')
    doc.saveas(tmp_path)
    return tmp_path

# --- USER INTERFACE ---
st.title("📐 KML to DXF Professional")
st.markdown("""
- **Scale:** Automatic Meters (UTM)
- **View:** Auto-Zoom to Extents
- **Context:** Automatic OSM Road Import
""")

uploaded_file = st.sidebar.file_uploader("Upload your KML file", type=['kml'])

if uploaded_file:
    # Save uploaded file to temp path for Fiona to read
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        path = tmp.name

    try:
        gdf = load_kml_properly(path)
        
        if not gdf.empty:
            st.sidebar.success(f"Successfully loaded {len(gdf)} items.")
            
            # Action Button
            if st.sidebar.button("🚀 Generate & Download DXF"):
                with st.spinner("Processing drawing..."):
                    dxf_file_path = convert_to_dxf_full(gdf)
                    with open(dxf_file_path, "rb") as f:
                        st.sidebar.download_button(
                            label="📥 Download AutoCAD File",
                            data=f,
                            file_name="Converted_Project_Meters.dxf",
                            mime="application/dxf"
                        )
            
            # Preview Map
            st.subheader("Map Preview (WGS84)")
            center = [gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()]
            m = folium.Map(location=center, zoom_start=16)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', 
                            attr='Google', name='Google Hybrid').add_to(m)
            
            # Plot data on Folium for visual verification
            for _, row in gdf.iterrows():
                if row.geometry.geom_type == 'Point':
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='red').add_to(m)
                else:
                    folium.PolyLine([[p[1], p[0]] for p in row.geometry.coords], color='lime', weight=3).add_to(m)
            
            folium_static(m, width=1000)
            
        else:
            st.error("The KML file contains no valid Point or LineString data.")

    except Exception as e:
        st.error(f"Error processing file: {e}")
    finally:
        # Clean up the temp KML file
        if os.path.exists(path):
            os.unlink(path)

st.sidebar.markdown("---")
st.sidebar.caption("v2.1 | Meters & Auto-Fit Enabled")
