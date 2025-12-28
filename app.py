import streamlit as st
import xml.etree.ElementTree as ET
import ezdxf
from ezdxf import colors
import tempfile
import os
import zipfile
from datetime import datetime
import io
import warnings

# Suppress warnings
warnings.filterwarnings('ignore')

# Set page configuration
st.set_page_config(
    page_title="KML to DXF Converter",
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
        margin-bottom: 2rem;
    }
    .success-box {
        background-color: #E8F5E9;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        border-left: 4px solid #4CAF50;
    }
    .warning-box {
        background-color: #FFF3E0;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        border-left: 4px solid #FF9800;
    }
    .stButton button {
        background-color: #1E88E5;
        color: white;
        font-weight: bold;
        border: none;
        padding: 0.5rem 2rem;
        border-radius: 5px;
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

class KMLtoDXFConverter:
    def __init__(self):
        self.stats = {
            'total_placemarks': 0,
            'points': 0,
            'lines': 0,
            'polygons': 0,
            'layers': set(),
            'entities_added': 0
        }
        self.geometries = []
        self.min_x = float('inf')
        self.max_x = float('-inf')
        self.min_y = float('inf')
        self.max_y = float('-inf')
    
    def parse_coordinates(self, coord_text):
        """Parse coordinates string to list of (x, y, z) tuples"""
        coords = []
        if not coord_text:
            return coords
        
        coord_text = coord_text.strip()
        lines = coord_text.split()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    # KML uses: longitude, latitude, elevation
                    lon = float(parts[0].strip())
                    lat = float(parts[1].strip())
                    
                    # Update bounds for scaling
                    self.min_x = min(self.min_x, lon)
                    self.max_x = max(self.max_x, lon)
                    self.min_y = min(self.min_y, lat)
                    self.max_y = max(self.max_y, lat)
                    
                    elev = 0.0
                    if len(parts) >= 3:
                        try:
                            elev = float(parts[2].strip())
                        except:
                            elev = 0.0
                    
                    # For DXF, we'll use x=longitude, y=latitude, z=elevation
                    coords.append((lon, lat, elev))
                except Exception as e:
                    continue
        
        return coords
    
    def kml_color_to_dxf(self, kml_color):
        """Convert KML color to DXF color index"""
        if not kml_color or not isinstance(kml_color, str):
            return 7  # White
        
        kml_color = kml_color.strip()
        if not kml_color.startswith('#'):
            return 7
        
        color_hex = kml_color[1:]
        
        if len(color_hex) == 8:
            try:
                # KML format: #AABBGGRR
                alpha = color_hex[0:2]
                blue = color_hex[2:4]
                green = color_hex[4:6]
                red = color_hex[6:8]
                
                # Convert to RGB values
                r = int(red, 16)
                g = int(green, 16)
                b = int(blue, 16)
                
                # Map to DXF colors (1-7 are standard colors)
                # Simple mapping based on dominant color
                if r > g and r > b:
                    return 1  # Red
                elif g > r and g > b:
                    return 3  # Green
                elif b > r and b > g:
                    return 5  # Blue
                elif r > 200 and g > 200:
                    return 2  # Yellow
                elif g > 200 and b > 200:
                    return 4  # Cyan
                elif r > 200 and b > 200:
                    return 6  # Magenta
                else:
                    # Calculate brightness
                    brightness = (r + g + b) / 3
                    if brightness > 128:
                        return 7  # White
                    else:
                        return 8  # Dark Grey
            except:
                return 7
        
        return 7
    
    def extract_style_info(self, placemark, root):
        """Extract style information from placemark"""
        style = {
            'color': 7,
            'width': 0.0,
            'layer': '0',
            'name': 'Unnamed',
            'description': ''
        }
        
        # Extract name
        name_elem = placemark.find('.//{*}name')
        if name_elem is not None and name_elem.text:
            name = name_elem.text.strip()
            style['name'] = name
            # Create layer name from placemark name
            safe_name = ''.join(c for c in name if c.isalnum() or c in ' _-')
            style['layer'] = safe_name[:30] if safe_name else 'Layer_0'
        
        # Extract description
        desc_elem = placemark.find('.//{*}description')
        if desc_elem is not None and desc_elem.text:
            style['description'] = desc_elem.text.strip()
        
        # Try to find style
        style_url = placemark.find('.//{*}styleUrl')
        if style_url is not None and style_url.text:
            style_id = style_url.text.strip().replace('#', '')
            if style_id:
                # Search for style in document
                for elem in root.iter():
                    if 'Style' in elem.tag and elem.get('id') == style_id:
                        # Get line color
                        line_style = elem.find('.//{*}LineStyle')
                        if line_style is not None:
                            color_elem = line_style.find('.//{*}color')
                            if color_elem is not None and color_elem.text:
                                style['color'] = self.kml_color_to_dxf(color_elem.text)
                            width_elem = line_style.find('.//{*}width')
                            if width_elem is not None and width_elem.text:
                                try:
                                    style['width'] = float(width_elem.text.strip())
                                except:
                                    style['width'] = 0.0
                        break
        
        return style
    
    def process_geometry(self, geometry_elem, style_info, geom_type):
        """Process geometry element"""
        coords_elem = geometry_elem.find('.//{*}coordinates')
        if coords_elem is not None and coords_elem.text:
            coordinates = self.parse_coordinates(coords_elem.text)
            
            if not coordinates:
                return False
            
            # For polygons, ensure they are closed
            if geom_type == 'POLYGON' and len(coordinates) >= 3:
                if coordinates[0] != coordinates[-1]:
                    coordinates.append(coordinates[0])
            
            self.geometries.append({
                'type': geom_type,
                'coordinates': coordinates,
                'style': style_info.copy(),
                'count': len(coordinates)
            })
            
            # Update statistics
            if geom_type == 'POINT':
                self.stats['points'] += len(coordinates)
            elif geom_type == 'LINESTRING':
                self.stats['lines'] += 1
            elif geom_type == 'POLYGON':
                self.stats['polygons'] += 1
            
            self.stats['layers'].add(style_info['layer'])
            return True
        
        return False
    
    def process_placemark(self, placemark, root):
        """Process a single placemark"""
        style_info = self.extract_style_info(placemark, root)
        processed = False
        
        # Check for Point
        point_elem = placemark.find('.//{*}Point')
        if point_elem is not None:
            if self.process_geometry(point_elem, style_info, 'POINT'):
                processed = True
        
        # Check for LineString
        line_elem = placemark.find('.//{*}LineString')
        if line_elem is not None:
            if self.process_geometry(line_elem, style_info, 'LINESTRING'):
                processed = True
        
        # Check for Polygon
        polygon_elem = placemark.find('.//{*}Polygon')
        if polygon_elem is not None:
            # For polygons, we need to get coordinates from outerBoundaryIs
            outer_boundary = polygon_elem.find('.//{*}outerBoundaryIs')
            if outer_boundary is not None:
                linear_ring = outer_boundary.find('.//{*}LinearRing')
                if linear_ring is not None:
                    # Create a mock geometry element with the coordinates
                    mock_geom = ET.Element('Polygon')
                    coords_elem = linear_ring.find('.//{*}coordinates')
                    if coords_elem is not None:
                        new_coords = ET.SubElement(mock_geom, 'coordinates')
                        new_coords.text = coords_elem.text
                        if self.process_geometry(mock_geom, style_info, 'POLYGON'):
                            processed = True
        
        # Check for MultiGeometry
        multi_elem = placemark.find('.//{*}MultiGeometry')
        if multi_elem is not None:
            for geom_elem in multi_elem:
                geom_type = geom_elem.tag.split('}')[-1] if '}' in geom_elem.tag else geom_elem.tag
                if geom_type == 'Point':
                    if self.process_geometry(geom_elem, style_info, 'POINT'):
                        processed = True
                elif geom_type == 'LineString':
                    if self.process_geometry(geom_elem, style_info, 'LINESTRING'):
                        processed = True
                elif geom_type == 'Polygon':
                    # Handle polygon in MultiGeometry
                    outer_boundary = geom_elem.find('.//{*}outerBoundaryIs')
                    if outer_boundary is not None:
                        linear_ring = outer_boundary.find('.//{*}LinearRing')
                        if linear_ring is not None:
                            mock_geom = ET.Element('Polygon')
                            coords_elem = linear_ring.find('.//{*}coordinates')
                            if coords_elem is not None:
                                new_coords = ET.SubElement(mock_geom, 'coordinates')
                                new_coords.text = coords_elem.text
                                if self.process_geometry(mock_geom, style_info, 'POLYGON'):
                                    processed = True
        
        return processed
    
    def parse_kml(self, kml_content):
        """Parse KML content"""
        try:
            # Decode if bytes
            if isinstance(kml_content, bytes):
                kml_content = kml_content.decode('utf-8', errors='ignore')
            
            # Clean content
            kml_content = kml_content.replace('\x00', '').strip()
            
            # Parse XML
            root = ET.fromstring(kml_content)
            
            # Find all placemarks
            placemarks = []
            
            # Try different namespace patterns
            namespace_patterns = [
                '{http://www.opengis.net/kml/2.2}',
                '{http://earth.google.com/kml/2.0}',
                '{http://earth.google.com/kml/2.1}',
                '{http://www.opengis.net/kml/2.1}',
                ''
            ]
            
            for ns in namespace_patterns:
                placemarks = root.findall(f'.//{ns}Placemark')
                if placemarks:
                    break
            
            if not placemarks:
                # Last resort: find any element with 'Placemark' in tag
                for elem in root.iter():
                    if 'Placemark' in elem.tag:
                        placemarks.append(elem)
            
            self.stats['total_placemarks'] = len(placemarks)
            
            # Process placemarks
            processed_count = 0
            for placemark in placemarks:
                try:
                    if self.process_placemark(placemark, root):
                        processed_count += 1
                except Exception as e:
                    st.warning(f"Warning: Could not process placemark: {e}")
                    continue
            
            # If no geometries found, try direct coordinate extraction
            if not self.geometries:
                self.extract_direct_coordinates(root)
            
            return len(self.geometries) > 0
            
        except Exception as e:
            st.error(f"Error parsing KML: {str(e)}")
            return False
    
    def extract_direct_coordinates(self, root):
        """Extract coordinates directly from any coordinate element"""
        coord_elems = root.findall('.//{*}coordinates')
        
        for elem in coord_elems:
            if elem.text:
                coordinates = self.parse_coordinates(elem.text)
                if coordinates:
                    if len(coordinates) == 1:
                        self.geometries.append({
                            'type': 'POINT',
                            'coordinates': coordinates,
                            'style': {'color': 7, 'layer': 'Extracted', 'name': 'Point'},
                            'count': 1
                        })
                        self.stats['points'] += 1
                    elif len(coordinates) == 2:
                        self.geometries.append({
                            'type': 'LINESTRING',
                            'coordinates': coordinates,
                            'style': {'color': 7, 'layer': 'Extracted', 'name': 'Line'},
                            'count': 2
                        })
                        self.stats['lines'] += 1
                    elif len(coordinates) >= 3:
                        self.geometries.append({
                            'type': 'POLYGON',
                            'coordinates': coordinates,
                            'style': {'color': 7, 'layer': 'Extracted', 'name': 'Polygon'},
                            'count': len(coordinates)
                        })
                        self.stats['polygons'] += 1
                    
                    self.stats['layers'].add('Extracted')
    
    def create_dxf(self, options):
        """Create DXF file from parsed geometries"""
        try:
            # Create DXF document
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # Add layers
            layer_names = list(self.stats['layers'])
            if not layer_names:
                layer_names = ['0']
            
            for layer_name in layer_names:
                try:
                    safe_name = str(layer_name)[:30].strip()
                    if safe_name:
                        doc.layers.new(name=safe_name, dxfattribs={'color': 7})
                except:
                    pass
            
            # Scale factor for better visualization
            scale_factor = 1000.0  # Scale up geographic coordinates
            
            # Process geometries
            entities_added = 0
            
            for geom in self.geometries:
                try:
                    geom_type = geom['type']
                    coordinates = geom['coordinates']
                    style = geom['style']
                    
                    layer_name = str(style.get('layer', '0'))[:30].strip() or '0'
                    color = style.get('color', 7)
                    
                    # Scale coordinates
                    scaled_coords = []
                    for x, y, z in coordinates:
                        # Apply scaling
                        scaled_x = x * scale_factor
                        scaled_y = y * scale_factor
                        scaled_z = z * scale_factor if z != 0 else 0.0
                        scaled_coords.append((scaled_x, scaled_y, scaled_z))
                    
                    if geom_type == 'POINT' and scaled_coords:
                        for x, y, z in scaled_coords:
                            msp.add_point((x, y, z), dxfattribs={
                                'layer': layer_name,
                                'color': color
                            })
                            entities_added += 1
                    
                    elif geom_type == 'LINESTRING' and len(scaled_coords) >= 2:
                        if len(scaled_coords) == 2 and options.get('simplify_lines', True):
                            # Add as LINE
                            msp.add_line(scaled_coords[0], scaled_coords[1], dxfattribs={
                                'layer': layer_name,
                                'color': color
                            })
                        else:
                            # Add as POLYLINE
                            msp.add_polyline3d(scaled_coords, dxfattribs={
                                'layer': layer_name,
                                'color': color
                            })
                        entities_added += 1
                    
                    elif geom_type == 'POLYGON' and len(scaled_coords) >= 3:
                        # Ensure polygon is closed
                        if scaled_coords[0] != scaled_coords[-1]:
                            scaled_coords.append(scaled_coords[0])
                        
                        # Add as LWPOLYLINE (2D for better compatibility)
                        if options.get('create_polyline', True):
                            # Convert to 2D
                            vertices_2d = [(x, y) for x, y, _ in scaled_coords]
                            msp.add_lwpolyline(vertices_2d, dxfattribs={
                                'layer': layer_name,
                                'color': color,
                                'closed': True
                            })
                            entities_added += 1
                        
                        # Optionally add hatch
                        if options.get('create_hatch', False):
                            try:
                                hatch = msp.add_hatch(color=color, dxfattribs={'layer': layer_name})
                                vertices_2d = [(x, y) for x, y, _ in scaled_coords]
                                hatch.paths.add_polyline_path(vertices_2d, is_closed=True)
                                entities_added += 1
                            except:
                                pass
                
                except Exception as e:
                    st.warning(f"Could not add geometry: {e}")
                    continue
            
            self.stats['entities_added'] = entities_added
            
            # If no entities added, add a dummy point to ensure file is not empty
            if entities_added == 0:
                st.warning("No valid geometries could be added to DXF. Adding reference point.")
                msp.add_point((0, 0, 0), dxfattribs={'layer': '0', 'color': 7})
                self.stats['entities_added'] = 1
            
            # Save to bytes
            dxf_bytes = io.BytesIO()
            doc.saveas(dxf_bytes)
            dxf_bytes.seek(0)
            
            # Verify file size
            file_size = len(dxf_bytes.getvalue())
            if file_size == 0:
                st.error("Generated DXF file is empty!")
                return None
            
            st.success(f"DXF created successfully with {entities_added} entities")
            return dxf_bytes
            
        except Exception as e:
            st.error(f"Error creating DXF: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return None
    
    def get_statistics(self):
        """Get conversion statistics"""
        return {
            'Total Geometries': len(self.geometries),
            'Points': self.stats['points'],
            'Lines': self.stats['lines'],
            'Polygons': self.stats['polygons'],
            'Layers': len(self.stats['layers']),
            'Entities Added': self.stats['entities_added'],
            'Coordinate Range': f"Lon: {self.min_x:.4f} to {self.max_x:.4f}, Lat: {self.min_y:.4f} to {self.max_y:.4f}"
        }

def main():
    # Header
    st.markdown('<h1 class="main-header">🗺️ KML to DXF Converter</h1>', unsafe_allow_html=True)
    st.markdown("Convert KML (Google Earth) files to DXF (CAD) format")
    
    # Initialize session state
    if 'converter' not in st.session_state:
        st.session_state.converter = None
    if 'dxf_bytes' not in st.session_state:
        st.session_state.dxf_bytes = None
    
    # Sidebar
    with st.sidebar:
        st.markdown("### ⚙️ Conversion Options")
        
        # Conversion options
        simplify_lines = st.checkbox("Simplify Lines", value=True,
                                     help="Convert 2-point lines to simple LINE entities")
        create_polyline = st.checkbox("Create Polylines", value=True,
                                      help="Create LWPOLYLINE for polygons")
        create_hatch = st.checkbox("Create Hatch", value=False,
                                   help="Add hatch patterns to polygons")
        scale_coords = st.checkbox("Scale Coordinates", value=True,
                                   help="Scale geographic coordinates for better visualization")
        
        options = {
            'simplify_lines': simplify_lines,
            'create_polyline': create_polyline,
            'create_hatch': create_hatch,
            'scale_coords': scale_coords
        }
        
        st.markdown("---")
        st.markdown("### 📊 Statistics")
        
        if st.session_state.converter:
            stats = st.session_state.converter.get_statistics()
            for key, value in stats.items():
                st.metric(key, value)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📤 Upload KML/KMZ File")
        
        uploaded_file = st.file_uploader(
            "Choose a file",
            type=['kml', 'kmz'],
            help="Upload KML or KMZ file from Google Earth"
        )
        
        if uploaded_file:
            # Display file info
            file_size_kb = len(uploaded_file.getvalue()) / 1024
            st.info(f"📄 **File:** {uploaded_file.name} | **Size:** {file_size_kb:.1f} KB")
            
            # Read file
            file_content = uploaded_file.getvalue()
            
            # Handle KMZ files
            if uploaded_file.name.lower().endswith('.kmz'):
                with st.spinner("Extracting KMZ..."):
                    try:
                        with zipfile.ZipFile(io.BytesIO(file_content)) as kmz:
                            kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]
                            if kml_files:
                                kml_files.sort(key=lambda x: 'doc.kml' in x.lower(), reverse=True)
                                with kmz.open(kml_files[0]) as f:
                                    file_content = f.read()
                                st.success(f"Extracted: {kml_files[0]}")
                            else:
                                st.error("No KML file found in KMZ")
                                return
                    except Exception as e:
                        st.error(f"KMZ extraction failed: {e}")
                        return
            
            # Convert button
            if st.button("🚀 Convert to DXF", type="primary", use_container_width=True):
                with st.spinner("Processing..."):
                    # Create converter
                    converter = KMLtoDXFConverter()
                    
                    # Parse KML
                    success = converter.parse_kml(file_content)
                    
                    if success:
                        st.session_state.converter = converter
                        
                        # Show stats
                        stats = converter.get_statistics()
                        st.success(f"✅ Parsed {stats['Total Geometries']} geometries")
                        
                        # Create DXF
                        with st.spinner("Creating DXF file..."):
                            dxf_bytes = converter.create_dxf(options)
                            
                            if dxf_bytes:
                                st.session_state.dxf_bytes = dxf_bytes
                                file_size_mb = len(dxf_bytes.getvalue()) / (1024 * 1024)
                                st.success(f"✅ DXF created: {file_size_mb:.2f} MB")
                            else:
                                st.error("❌ Failed to create DXF")
                    else:
                        st.error("❌ Failed to parse KML")
            
            # Download section
            if st.session_state.dxf_bytes:
                st.markdown("### 📥 Download DXF")
                
                # Generate filename
                if uploaded_file:
                    base_name = os.path.splitext(uploaded_file.name)[0]
                    if base_name.lower().endswith('.kmz'):
                        base_name = base_name[:-4]
                    filename = f"{base_name}.dxf"
                else:
                    filename = f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
                
                # Download button
                file_size = len(st.session_state.dxf_bytes.getvalue())
                st.download_button(
                    label=f"⬇️ Download DXF ({file_size/1024:.1f} KB)",
                    data=st.session_state.dxf_bytes,
                    file_name=filename,
                    mime="application/dxf",
                    use_container_width=True
                )
                
                # Preview info
                with st.expander("📋 Conversion Details"):
                    if st.session_state.converter:
                        stats = st.session_state.converter.get_statistics()
                        for key, value in stats.items():
                            st.write(f"**{key}:** {value}")
                        
                        # Show sample coordinates
                        if st.session_state.converter.geometries:
                            geom = st.session_state.converter.geometries[0]
                            if geom['coordinates']:
                                coord = geom['coordinates'][0]
                                st.write("**Sample Coordinate:**")
                                st.code(f"Longitude: {coord[0]:.6f}\nLatitude: {coord[1]:.6f}\nElevation: {coord[2]:.1f}")
    
    with col2:
        st.markdown("### 📝 Quick Guide")
        
        st.markdown("""
        **1.** Upload KML/KMZ file
        
        **2.** Adjust conversion options
        
        **3.** Click "Convert to DXF"
        
        **4.** Download the DXF file
        
        **Supported:**
        - ✅ Points
        - ✅ Lines/Paths
        - ✅ Polygons
        - ✅ Colors
        - ✅ Layers
        - ✅ KMZ files
        """)
        
        st.markdown("---")
        st.markdown("### 🛠️ Troubleshooting")
        
        st.markdown("""
        **Empty DXF?**
        - Try different KML file
        - Check KML contains valid geometries
        - Enable all conversion options
        
        **Can't open DXF?**
        - Use AutoCAD or compatible viewer
        - Try DraftSight or LibreCAD
        - Ensure file size > 0
        
        **Coordinates wrong?**
        - Coordinates are geographic
        - No projection applied
        - Scale may be needed
        """)
        
        # Sample KML
        st.markdown("---")
        st.markdown("### 🧪 Test Sample")
        
        sample_kml = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark>
    <name>Test Point</name>
    <Point>
      <coordinates>110.0,-7.0,0</coordinates>
    </Point>
  </Placemark>
  <Placemark>
    <name>Test Line</name>
    <LineString>
      <coordinates>
        110.0,-7.0,0
        110.1,-7.1,0
        110.2,-7.2,0
      </coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>Test Polygon</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            110.0,-7.0,0
            110.1,-7.0,0
            110.1,-7.1,0
            110.0,-7.1,0
            110.0,-7.0,0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>'''
        
        st.download_button(
            "Download Sample KML",
            sample_kml,
            "sample.kml",
            "application/vnd.google-earth.kml+xml",
            use_container_width=True
        )

    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666;'>
        <p><strong>KML to DXF Converter</strong> | v3.0 | Streamlit + ezdxf</p>
        <p style='font-size: 0.9rem;'>For accurate CAD work, post-process coordinates in CAD software</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
