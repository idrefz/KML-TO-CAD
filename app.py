import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import zipfile
import os
from datetime import datetime
import numpy as np

# Set page configuration
st.set_page_config(
    page_title="KML to Map Visualizer",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 1rem;
    }
    .map-container {
        border-radius: 10px;
        border: 1px solid #ddd;
        padding: 10px;
        background-color: white;
    }
    .legend-box {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        border-left: 4px solid #1E88E5;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

class KMLVisualizer:
    def __init__(self):
        self.points = []
        self.lines = []
        self.polygons = []
        self.stats = {
            'total_points': 0,
            'total_lines': 0,
            'total_polygons': 0,
            'layers': set()
        }
    
    def parse_coordinates(self, coord_text):
        """Parse coordinates string"""
        coords = []
        if not coord_text:
            return coords
        
        for line in coord_text.strip().split():
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    elev = float(parts[2]) if len(parts) >= 3 else 0.0
                    coords.append((lon, lat, elev))
                except:
                    continue
        return coords
    
    def extract_color_from_style(self, style_url, root):
        """Extract color from KML style"""
        if not style_url:
            return None
        
        style_id = style_url.replace('#', '')
        
        # Find the style definition
        for elem in root.iter():
            if 'Style' in elem.tag and elem.get('id') == style_id:
                line_style = elem.find('.//{*}LineStyle')
                if line_style is not None:
                    color_elem = line_style.find('.//{*}color')
                    if color_elem is not None and color_elem.text:
                        # KML color: #AABBGGRR
                        color_hex = color_elem.text.strip()
                        if color_hex.startswith('#') and len(color_hex) == 9:
                            # Convert to #RRGGBB
                            rr = color_hex[7:9]
                            gg = color_hex[5:7]
                            bb = color_hex[3:5]
                            return f'#{rr}{gg}{bb}'
        return None
    
    def process_kml(self, kml_content):
        """Process KML content and extract geometries"""
        try:
            # Parse XML
            root = ET.fromstring(kml_content)
            
            # Find all placemarks
            placemarks = []
            namespaces = [
                '{http://www.opengis.net/kml/2.2}',
                '{http://earth.google.com/kml/2.0}',
                '{http://earth.google.com/kml/2.1}',
                ''
            ]
            
            for ns in namespaces:
                placemarks = root.findall(f'.//{ns}Placemark')
                if placemarks:
                    break
            
            for pm in placemarks:
                # Get name
                name_elem = pm.find('.//{*}name')
                name = name_elem.text if name_elem is not None else 'Unnamed'
                
                # Get style color
                style_elem = pm.find('.//{*}styleUrl')
                style_url = style_elem.text if style_elem is not None else None
                color = self.extract_color_from_style(style_url, root) if style_url else '#1E88E5'
                
                # Process Point
                point = pm.find('.//{*}Point')
                if point is not None:
                    coords_elem = point.find('.//{*}coordinates')
                    if coords_elem is not None and coords_elem.text:
                        coords = self.parse_coordinates(coords_elem.text)
                        for lon, lat, elev in coords:
                            self.points.append({
                                'name': name,
                                'longitude': lon,
                                'latitude': lat,
                                'elevation': elev,
                                'color': color,
                                'type': 'Point'
                            })
                            self.stats['total_points'] += 1
                            self.stats['layers'].add(name)
                
                # Process LineString
                line = pm.find('.//{*}LineString')
                if line is not None:
                    coords_elem = line.find('.//{*}coordinates')
                    if coords_elem is not None and coords_elem.text:
                        coords = self.parse_coordinates(coords_elem.text)
                        if len(coords) >= 2:
                            # Extract coordinates for the line
                            lons = [c[0] for c in coords]
                            lats = [c[1] for c in coords]
                            
                            self.lines.append({
                                'name': name,
                                'longitudes': lons,
                                'latitudes': lats,
                                'coordinates': coords,
                                'color': color,
                                'type': 'Line'
                            })
                            self.stats['total_lines'] += 1
                            self.stats['layers'].add(name)
                
                # Process Polygon
                polygon = pm.find('.//{*}Polygon')
                if polygon is not None:
                    outer = polygon.find('.//{*}outerBoundaryIs')
                    if outer is not None:
                        ring = outer.find('.//{*}LinearRing')
                        if ring is not None:
                            coords_elem = ring.find('.//{*}coordinates')
                            if coords_elem is not None and coords_elem.text:
                                coords = self.parse_coordinates(coords_elem.text)
                                if len(coords) >= 3:
                                    # Ensure polygon is closed
                                    if coords[0] != coords[-1]:
                                        coords.append(coords[0])
                                    
                                    lons = [c[0] for c in coords]
                                    lats = [c[1] for c in coords]
                                    
                                    self.polygons.append({
                                        'name': name,
                                        'longitudes': lons,
                                        'latitudes': lats,
                                        'coordinates': coords,
                                        'color': color,
                                        'type': 'Polygon',
                                        'fill_color': color + '80'  # Add transparency
                                    })
                                    self.stats['total_polygons'] += 1
                                    self.stats['layers'].add(name)
            
            return True
            
        except Exception as e:
            st.error(f"Error processing KML: {e}")
            return False
    
    def create_dataframes(self):
        """Create pandas DataFrames for visualization"""
        points_df = pd.DataFrame(self.points) if self.points else pd.DataFrame()
        
        # Create lines DataFrame
        lines_data = []
        for line in self.lines:
            for lon, lat in zip(line['longitudes'], line['latitudes']):
                lines_data.append({
                    'name': line['name'],
                    'longitude': lon,
                    'latitude': lat,
                    'color': line['color'],
                    'type': 'Line'
                })
        lines_df = pd.DataFrame(lines_data) if lines_data else pd.DataFrame()
        
        # Create polygons DataFrame
        polygons_data = []
        for poly in self.polygons:
            for lon, lat in zip(poly['longitudes'], poly['latitudes']):
                polygons_data.append({
                    'name': poly['name'],
                    'longitude': lon,
                    'latitude': lat,
                    'color': poly['color'],
                    'fill_color': poly['fill_color'],
                    'type': 'Polygon'
                })
        polygons_df = pd.DataFrame(polygons_data) if polygons_data else pd.DataFrame()
        
        return points_df, lines_df, polygons_df
    
    def plot_map(self, map_style='open-street-map', show_legend=True):
        """Create interactive map with Plotly"""
        fig = go.Figure()
        
        # Add polygons first (so they're underneath)
        for poly in self.polygons:
            fig.add_trace(go.Scattermapbox(
                lon=poly['longitudes'],
                lat=poly['latitudes'],
                mode='lines',
                fill='toself',
                fillcolor=poly.get('fill_color', '#1E88E540'),
                line=dict(color=poly['color'], width=2),
                name=poly['name'],
                hoverinfo='text',
                text=f"<b>{poly['name']}</b><br>Type: Polygon<br>Points: {len(poly['coordinates'])}",
                showlegend=show_legend
            ))
        
        # Add lines
        for line in self.lines:
            fig.add_trace(go.Scattermapbox(
                lon=line['longitudes'],
                lat=line['latitudes'],
                mode='lines',
                line=dict(color=line['color'], width=3),
                name=line['name'],
                hoverinfo='text',
                text=f"<b>{line['name']}</b><br>Type: Line<br>Points: {len(line['coordinates'])}",
                showlegend=show_legend
            ))
        
        # Add points last (so they're on top)
        if self.points:
            points_df = pd.DataFrame(self.points)
            fig.add_trace(go.Scattermapbox(
                lon=points_df['longitude'],
                lat=points_df['latitude'],
                mode='markers+text',
                marker=dict(
                    size=10,
                    color=points_df['color'],
                    symbol='circle'
                ),
                text=points_df['name'],
                textposition="top right",
                name='Points',
                hoverinfo='text',
                hovertext=points_df.apply(
                    lambda row: f"<b>{row['name']}</b><br>Type: Point<br>Lat: {row['latitude']:.4f}<br>Lon: {row['longitude']:.4f}",
                    axis=1
                ),
                showlegend=show_legend
            ))
        
        # Calculate map bounds
        all_lons = []
        all_lats = []
        
        for point in self.points:
            all_lons.append(point['longitude'])
            all_lats.append(point['latitude'])
        
        for line in self.lines:
            all_lons.extend(line['longitudes'])
            all_lats.extend(line['latitudes'])
        
        for poly in self.polygons:
            all_lons.extend(poly['longitudes'])
            all_lats.extend(poly['latitudes'])
        
        if all_lons and all_lats:
            center_lon = np.mean(all_lons)
            center_lat = np.mean(all_lats)
            
            # Add some padding
            lon_range = max(all_lons) - min(all_lons)
            lat_range = max(all_lats) - min(all_lats)
            padding = max(lon_range, lat_range) * 0.1
            
            bounds = {
                'min_lon': min(all_lons) - padding,
                'max_lon': max(all_lons) + padding,
                'min_lat': min(all_lats) - padding,
                'max_lat': max(all_lats) + padding
            }
        else:
            # Default to Jakarta if no coordinates
            center_lon = 106.8456
            center_lat = -6.2088
            bounds = None
        
        # Configure map layout
        fig.update_layout(
            mapbox=dict(
                style=map_style,
                center=dict(lon=center_lon, lat=center_lat),
                zoom=10 if bounds and (bounds['max_lon'] - bounds['min_lon'] < 1) else 8
            ),
            margin=dict(l=0, r=0, t=30, b=0),
            height=600,
            showlegend=show_legend,
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01,
                bgcolor='rgba(255, 255, 255, 0.8)'
            ),
            title=dict(
                text="KML Data Visualization",
                x=0.5,
                xanchor='center'
            )
        )
        
        # If bounds are available, set them
        if bounds:
            fig.update_layout(
                mapbox=dict(
                    bounds=dict(
                        west=bounds['min_lon'],
                        east=bounds['max_lon'],
                        south=bounds['min_lat'],
                        north=bounds['max_lat']
                    )
                )
            )
        
        return fig
    
    def create_summary_table(self):
        """Create summary statistics table"""
        summary_data = {
            'Metric': ['Total Points', 'Total Lines', 'Total Polygons', 'Total Layers'],
            'Value': [
                self.stats['total_points'],
                self.stats['total_lines'],
                self.stats['total_polygons'],
                len(self.stats['layers'])
            ]
        }
        return pd.DataFrame(summary_data)

# Initialize session state
if 'visualizer' not in st.session_state:
    st.session_state.visualizer = None
if 'map_fig' not in st.session_state:
    st.session_state.map_fig = None
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

# Title
st.markdown('<h1 class="main-header">🗺️ KML Map Visualizer</h1>', unsafe_allow_html=True)
st.markdown("Visualize KML/KMZ files directly in your browser with interactive maps")

# Sidebar
with st.sidebar:
    st.header("⚙️ Map Settings")
    
    map_style = st.selectbox(
        "Map Style",
        ['open-street-map', 'carto-positron', 'carto-darkmatter', 
         'stamen-terrain', 'stamen-toner', 'stamen-watercolor'],
        help="Choose the base map style"
    )
    
    show_legend = st.checkbox("Show Legend", value=True)
    
    auto_zoom = st.checkbox("Auto Zoom to Data", value=True)
    
    st.markdown("---")
    st.header("📊 Data Summary")
    
    if st.session_state.data_loaded and st.session_state.visualizer:
        stats = st.session_state.visualizer.stats
        col1, col2 = st.columns(2)
        col1.metric("Points", stats['total_points'])
        col1.metric("Lines", stats['total_lines'])
        col2.metric("Polygons", stats['total_polygons'])
        col2.metric("Layers", len(stats['layers']))
    
    st.markdown("---")
    st.header("💡 Tips")
    st.markdown("""
    1. Upload KML/KMZ file
    2. Map loads automatically
    3. Hover for details
    4. Use mouse to zoom/pan
    5. Toggle legend on/off
    """)

# Main content area
col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("📤 Upload KML/KMZ File")
    
    uploaded_file = st.file_uploader(
        "Choose a KML or KMZ file",
        type=['kml', 'kmz'],
        help="Supported: Google Earth KML/KMZ files",
        label_visibility="collapsed"
    )
    
    if uploaded_file is not None:
        # Show file info
        file_size = len(uploaded_file.getvalue()) / 1024
        st.info(f"📄 **File:** {uploaded_file.name} | **Size:** {file_size:.1f} KB")
        
        # Read file content
        file_content = uploaded_file.getvalue()
        
        # Handle KMZ files
        if uploaded_file.name.lower().endswith('.kmz'):
            with st.spinner("Extracting KMZ file..."):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_content), 'r') as kmz:
                        kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]
                        if kml_files:
                            kml_files.sort(key=lambda x: 'doc.kml' in x.lower(), reverse=True)
                            with kmz.open(kml_files[0]) as f:
                                file_content = f.read()
                            st.success(f"✅ Extracted: {kml_files[0]}")
                        else:
                            st.error("❌ No KML file found in KMZ archive")
                            st.stop()
                except Exception as e:
                    st.error(f"❌ Error extracting KMZ: {e}")
                    st.stop()
        
        # Process KML
        with st.spinner("Processing KML data..."):
            visualizer = KMLVisualizer()
            
            if visualizer.process_kml(file_content):
                st.session_state.visualizer = visualizer
                st.session_state.data_loaded = True
                
                # Create map
                with st.spinner("Generating map..."):
                    map_fig = visualizer.plot_map(map_style, show_legend)
                    st.session_state.map_fig = map_fig
                
                st.success("✅ KML data loaded successfully!")
            else:
                st.error("❌ Failed to process KML file")
                st.stop()
    
    # Display map
    st.subheader("🗺️ Interactive Map")
    
    if st.session_state.map_fig:
        st.plotly_chart(st.session_state.map_fig, use_container_width=True)
        
        # Map controls
        with st.expander("🗺️ Map Controls", expanded=False):
            col_ctrl1, col_ctrl2 = st.columns(2)
            with col_ctrl1:
                if st.button("🔍 Reset View"):
                    if st.session_state.visualizer:
                        new_fig = st.session_state.visualizer.plot_map(map_style, show_legend)
                        st.session_state.map_fig = new_fig
                        st.rerun()
            
            with col_ctrl2:
                if st.button("🔄 Refresh Map"):
                    if st.session_state.visualizer:
                        new_fig = st.session_state.visualizer.plot_map(map_style, show_legend)
                        st.session_state.map_fig = new_fig
                        st.rerun()
    else:
        # Show placeholder map
        st.info("👆 Upload a KML/KMZ file to visualize the data")
        
        # Sample map
        fig = go.Figure()
        fig.update_layout(
            mapbox=dict(
                style=map_style,
                center=dict(lon=106.8456, lat=-6.2088),
                zoom=5
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("📋 Data Summary")
    
    if st.session_state.data_loaded and st.session_state.visualizer:
        # Summary table
        summary_df = st.session_state.visualizer.create_summary_table()
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True
        )
        
        # Layers list
        with st.expander("🏷️ Layers", expanded=True):
            layers = list(st.session_state.visualizer.stats['layers'])
            if layers:
                for layer in sorted(layers)[:10]:  # Show first 10
                    st.write(f"• {layer}")
                if len(layers) > 10:
                    st.caption(f"... and {len(layers) - 10} more layers")
            else:
                st.write("No named layers found")
        
        # Sample coordinates
        with st.expander("📍 Sample Coordinates", expanded=False):
            if st.session_state.visualizer.points:
                point = st.session_state.visualizer.points[0]
                st.code(f"Lat: {point['latitude']:.6f}\nLon: {point['longitude']:.6f}")
            elif st.session_state.visualizer.lines:
                line = st.session_state.visualizer.lines[0]
                if line['coordinates']:
                    coord = line['coordinates'][0]
                    st.code(f"Lat: {coord[1]:.6f}\nLon: {coord[0]:.6f}")
        
        # Export options
        st.markdown("---")
        st.subheader("📤 Export Data")
        
        if st.button("📊 Export as CSV", use_container_width=True):
            if st.session_state.visualizer:
                # Create combined dataframe
                all_data = []
                
                # Add points
                for point in st.session_state.visualizer.points:
                    all_data.append({
                        'name': point['name'],
                        'type': 'Point',
                        'longitude': point['longitude'],
                        'latitude': point['latitude'],
                        'elevation': point['elevation'],
                        'color': point['color']
                    })
                
                # Add lines (simplified - one row per line)
                for line in st.session_state.visualizer.lines:
                    all_data.append({
                        'name': line['name'],
                        'type': 'Line',
                        'longitude': np.mean(line['longitudes']),
                        'latitude': np.mean(line['latitudes']),
                        'elevation': 0,
                        'color': line['color'],
                        'num_points': len(line['coordinates'])
                    })
                
                # Add polygons
                for poly in st.session_state.visualizer.polygons:
                    all_data.append({
                        'name': poly['name'],
                        'type': 'Polygon',
                        'longitude': np.mean(poly['longitudes']),
                        'latitude': np.mean(poly['latitudes']),
                        'elevation': 0,
                        'color': poly['color'],
                        'num_points': len(poly['coordinates'])
                    })
                
                if all_data:
                    df = pd.DataFrame(all_data)
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "⬇️ Download CSV",
                        csv,
                        "kml_data.csv",
                        "text/csv",
                        use_container_width=True
                    )
    
    else:
        st.info("No data loaded yet")
        
        # Quick stats placeholder
        placeholder_data = {
            'Metric': ['Points', 'Lines', 'Polygons', 'Layers'],
            'Value': ['-', '-', '-', '-']
        }
        st.dataframe(
            pd.DataFrame(placeholder_data),
            use_container_width=True,
            hide_index=True
        )

# Data tables section
if st.session_state.data_loaded and st.session_state.visualizer:
    st.markdown("---")
    st.subheader("📊 Detailed Data")
    
    tab1, tab2, tab3 = st.tabs(["Points", "Lines", "Polygons"])
    
    with tab1:
        if st.session_state.visualizer.points:
            points_df = pd.DataFrame(st.session_state.visualizer.points)
            st.dataframe(
                points_df[['name', 'longitude', 'latitude', 'elevation', 'color']],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No points in this KML file")
    
    with tab2:
        if st.session_state.visualizer.lines:
            lines_data = []
            for line in st.session_state.visualizer.lines:
                lines_data.append({
                    'name': line['name'],
                    'points': len(line['coordinates']),
                    'color': line['color'],
                    'start': f"{line['coordinates'][0][1]:.4f}, {line['coordinates'][0][0]:.4f}",
                    'end': f"{line['coordinates'][-1][1]:.4f}, {line['coordinates'][-1][0]:.4f}"
                })
            lines_df = pd.DataFrame(lines_data)
            st.dataframe(lines_df, use_container_width=True, hide_index=True)
        else:
            st.info("No lines in this KML file")
    
    with tab3:
        if st.session_state.visualizer.polygons:
            polygons_data = []
            for poly in st.session_state.visualizer.polygons:
                polygons_data.append({
                    'name': poly['name'],
                    'points': len(poly['coordinates']),
                    'color': poly['color'],
                    'center': f"{np.mean(poly['latitudes']):.4f}, {np.mean(poly['longitudes']):.4f}"
                })
            polygons_df = pd.DataFrame(polygons_data)
            st.dataframe(polygons_df, use_container_width=True, hide_index=True)
        else:
            st.info("No polygons in this KML file")

# Sample KML section
with st.expander("🧪 Try Sample KML", expanded=False):
    st.markdown("Download a sample KML file to test the visualizer:")
    
    sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Jakarta Area Map</name>
  
  <Style id="redLine">
    <LineStyle>
      <color>ff0000ff</color>
      <width>3</width>
    </LineStyle>
  </Style>
  
  <Style id="greenPolygon">
    <LineStyle>
      <color>ff00ff00</color>
      <width>2</width>
    </LineStyle>
    <PolyStyle>
      <color>8000ff00</color>
    </PolyStyle>
  </Style>
  
  <Style id="bluePoint">
    <IconStyle>
      <color>ffff0000</color>
    </IconStyle>
  </Style>
  
  <Placemark>
    <name>Monas</name>
    <styleUrl>#bluePoint</styleUrl>
    <Point>
      <coordinates>106.826959,-6.175392,0</coordinates>
    </Point>
  </Placemark>
  
  <Placemark>
    <name>Bundaran HI</name>
    <Point>
      <coordinates>106.823611,-6.194444,0</coordinates>
    </Point>
  </Placemark>
  
  <Placemark>
    <name>Main Road</name>
    <styleUrl>#redLine</styleUrl>
    <LineString>
      <coordinates>
        106.826959,-6.175392,0
        106.823611,-6.194444,0
        106.835000,-6.210000,0
      </coordinates>
    </LineString>
  </Placemark>
  
  <Placemark>
    <name>Central Park</name>
    <styleUrl>#greenPolygon</styleUrl>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            106.790,-6.180,0
            106.800,-6.180,0
            106.800,-6.190,0
            106.790,-6.190,0
            106.790,-6.180,0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
  
  <Placemark>
    <name>Business District</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            106.810,-6.200,0
            106.820,-6.200,0
            106.820,-6.210,0
            106.810,-6.210,0
            106.810,-6.200,0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>"""
    
    st.download_button(
        "Download Sample KML",
        sample_kml,
        "sample_jakarta.kml",
        "text/xml",
        use_container_width=True
    )

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666;'>
    <p><strong>KML Map Visualizer</strong> • Interactive visualization of KML data using Plotly</p>
    <p style='font-size: 0.9rem;'>Supports Points, Lines, Polygons with colors and layers</p>
    </div>
    """,
    unsafe_allow_html=True
)
