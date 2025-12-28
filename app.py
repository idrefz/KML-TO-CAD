import streamlit as st
import xml.etree.ElementTree as ET
import ezdxf
from ezdxf import colors
import tempfile
import os
import zipfile
from datetime import datetime
import base64
import io

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
    .sub-header {
        font-size: 1.5rem;
        color: #424242;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .info-box {
        background-color: #E3F2FD;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        border-left: 4px solid #1E88E5;
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
    .stButton button:hover {
        background-color: #1565C0;
    }
    .stats-box {
        background-color: #F5F5F5;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .file-uploader {
        border: 2px dashed #1E88E5;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

class KMLtoDXFConverter:
    def __init__(self):
        self.namespace = {'kml': 'http://www.opengis.net/kml/2.2'}
        self.stats = {
            'total_placemarks': 0,
            'points': 0,
            'lines': 0,
            'polygons': 0,
            'layers': set(),
            'multigeometries': 0
        }
        self.geometries = []
    
    def parse_coordinates(self, coord_text):
        """Parse coordinates string to list of (x, y, z) tuples"""
        coords = []
        if not coord_text:
            return coords
        
        lines = coord_text.strip().split()
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    x = float(parts[0])  # Longitude
                    y = float(parts[1])  # Latitude
                    z = float(parts[2]) if len(parts) >= 3 else 0.0  # Elevation
                    coords.append((x, y, z))
                except ValueError:
                    continue
        return coords
    
    def kml_color_to_dxf(self, kml_color):
        """Convert KML color to DXF color index"""
        if not kml_color or not kml_color.startswith('#'):
            return 7  # White
        
        # KML: #aabbggrr to RGB
        color_hex = kml_color[1:]
        if len(color_hex) == 8:
            # Convert to grayscale to determine brightness
            try:
                rr = int(color_hex[6:8], 16)
                gg = int(color_hex[4:6], 16)
                bb = int(color_hex[2:4], 16)
                brightness = (rr + gg + bb) / 3
                
                # Map brightness to DXF color index
                if brightness < 30:
                    return 0    # Black
                elif brightness < 60:
                    return 8    # Dark Grey
                elif brightness < 90:
                    return 7    # White
                elif brightness < 120:
                    return 1    # Red
                elif brightness < 150:
                    return 2    # Yellow
                elif brightness < 180:
                    return 3    # Green
                elif brightness < 210:
                    return 4    # Cyan
                elif brightness < 240:
                    return 5    # Blue
                else:
                    return 6    # Magenta
            except:
                return 7
        
        return 7
    
    def find_style_by_id(self, root, style_id):
        """Find style definition by ID in the XML tree"""
        # Search in entire document
        for elem in root.iter():
            if elem.tag.endswith('}Style'):
                elem_id = elem.get('id')
                if elem_id == style_id:
                    return elem
        return None
    
    def extract_style_info(self, placemark, root):
        """Extract style information from placemark"""
        style = {
            'color': 7,      # Default white
            'width': 0.0,    # Default line width
            'layer': '0',    # Default layer
            'filled': True,  # Default fill
            'name': 'Unnamed'
        }
        
        # Get name for layer and entity name
        name_elem = placemark.find('.//{*}name')
        if name_elem is not None and name_elem.text:
            safe_name = ''.join(c for c in name_elem.text if c.isalnum() or c in ' _-')
            style['layer'] = safe_name[:31] if safe_name else 'Layer_0'
            style['name'] = name_elem.text
        else:
            style['layer'] = 'Layer_0'
            style['name'] = 'Unnamed'
        
        # Try to get styleUrl
        style_url = placemark.find('.//{*}styleUrl')
        if style_url is not None and style_url.text:
            style_id = style_url.text.replace('#', '')
            style_def = self.find_style_by_id(root, style_id)
            
            if style_def is not None:
                # Line style
                line_style = style_def.find('.//{*}LineStyle')
                if line_style is not None:
                    color_elem = line_style.find('.//{*}color')
                    if color_elem is not None and color_elem.text:
                        style['color'] = self.kml_color_to_dxf(color_elem.text)
                    
                    width_elem = line_style.find('.//{*}width')
                    if width_elem is not None and width_elem.text:
                        try:
                            style['width'] = float(width_elem.text)
                        except ValueError:
                            style['width'] = 0.0
                
                # Polygon style
                poly_style = style_def.find('.//{*}PolyStyle')
                if poly_style is not None:
                    fill_elem = poly_style.find('.//{*}fill')
                    if fill_elem is not None and fill_elem.text:
                        style['filled'] = fill_elem.text == '1'
        
        return style
    
    def process_point(self, geometry_elem, style_info):
        """Process Point geometry"""
        coords_elem = geometry_elem.find('.//{*}coordinates')
        if coords_elem is not None and coords_elem.text:
            coordinates = self.parse_coordinates(coords_elem.text)
            if coordinates:
                self.geometries.append({
                    'type': 'POINT',
                    'coordinates': coordinates,
                    'style': style_info,
                    'count': len(coordinates)
                })
                self.stats['points'] += len(coordinates)
                return True
        return False
    
    def process_linestring(self, geometry_elem, style_info):
        """Process LineString geometry"""
        coords_elem = geometry_elem.find('.//{*}coordinates')
        if coords_elem is not None and coords_elem.text:
            coordinates = self.parse_coordinates(coords_elem.text)
            if len(coordinates) >= 2:
                self.geometries.append({
                    'type': 'LINESTRING',
                    'coordinates': coordinates,
                    'style': style_info,
                    'count': len(coordinates)
                })
                self.stats['lines'] += 1
                return True
        return False
    
    def process_polygon(self, geometry_elem, style_info):
        """Process Polygon geometry"""
        # Get outer boundary
        outer_boundary = geometry_elem.find('.//{*}outerBoundaryIs')
        if outer_boundary is not None:
            linear_ring = outer_boundary.find('.//{*}LinearRing')
            if linear_ring is not None:
                coords_elem = linear_ring.find('.//{*}coordinates')
                if coords_elem is not None and coords_elem.text:
                    coordinates = self.parse_coordinates(coords_elem.text)
                    if len(coordinates) >= 3:
                        # Ensure polygon is closed
                        if coordinates[0] != coordinates[-1]:
                            coordinates.append(coordinates[0])
                        
                        self.geometries.append({
                            'type': 'POLYGON',
                            'coordinates': coordinates,
                            'style': style_info,
                            'count': len(coordinates)
                        })
                        self.stats['polygons'] += 1
                        
                        # Also process inner boundaries (holes)
                        inner_boundaries = geometry_elem.findall('.//{*}innerBoundaryIs')
                        for inner in inner_boundaries:
                            inner_ring = inner.find('.//{*}LinearRing')
                            if inner_ring is not None:
                                inner_coords_elem = inner_ring.find('.//{*}coordinates')
                                if inner_coords_elem is not None and inner_coords_elem.text:
                                    inner_coords = self.parse_coordinates(inner_coords_elem.text)
                                    if len(inner_coords) >= 3:
                                        if inner_coords[0] != inner_coords[-1]:
                                            inner_coords.append(inner_coords[0])
                                        
                                        self.geometries.append({
                                            'type': 'POLYGON_HOLE',
                                            'coordinates': inner_coords,
                                            'style': style_info,
                                            'count': len(inner_coords)
                                        })
                        return True
        return False
    
    def process_placemark(self, placemark, root):
        """Process a single placemark"""
        style_info = self.extract_style_info(placemark, root)
        self.stats['layers'].add(style_info['layer'])
        
        processed = False
        
        # Check for simple geometries first
        point_elem = placemark.find('.//{*}Point')
        if point_elem is not None:
            processed = self.process_point(point_elem, style_info)
        
        if not processed:
            line_elem = placemark.find('.//{*}LineString')
            if line_elem is not None:
                processed = self.process_linestring(line_elem, style_info)
        
        if not processed:
            polygon_elem = placemark.find('.//{*}Polygon')
            if polygon_elem is not None:
                processed = self.process_polygon(polygon, style_info)
        
        # Check for MultiGeometry
        if not processed:
            multi_elem = placemark.find('.//{*}MultiGeometry')
            if multi_elem is not None:
                self.stats['multigeometries'] += 1
                # Process each geometry in MultiGeometry
                for geom_elem in multi_elem:
                    geom_type = geom_elem.tag.split('}')[-1] if '}' in geom_elem.tag else geom_elem.tag
                    
                    if geom_type == 'Point':
                        self.process_point(geom_elem, style_info)
                    elif geom_type == 'LineString':
                        self.process_linestring(geom_elem, style_info)
                    elif geom_type == 'Polygon':
                        self.process_polygon(geom_elem, style_info)
                processed = True
        
        return processed
    
    def parse_kml(self, kml_content):
        """Parse KML content"""
        try:
            # Parse XML
            try:
                root = ET.fromstring(kml_content)
            except ET.ParseError:
                # Try to fix common XML issues
                kml_content = kml_content.decode('utf-8') if isinstance(kml_content, bytes) else kml_content
                # Remove any null characters
                kml_content = kml_content.replace('\x00', '')
                root = ET.fromstring(kml_content)
            
            # Find all placemarks (handle multiple namespaces)
            placemarks = []
            
            # Try different namespace approaches
            placemarks = root.findall('.//{http://www.opengis.net/kml/2.2}Placemark')
            if not placemarks:
                placemarks = root.findall('.//{http://earth.google.com/kml/2.0}Placemark')
            if not placemarks:
                placemarks = root.findall('.//{http://earth.google.com/kml/2.1}Placemark')
            if not placemarks:
                # Try without namespace
                placemarks = root.findall('.//Placemark')
            if not placemarks:
                # Try wildcard namespace
                placemarks = root.findall('.//{*}Placemark')
            
            self.stats['total_placemarks'] = len(placemarks)
            
            # Process each placemark
            processed_count = 0
            for placemark in placemarks:
                if self.process_placemark(placemark, root):
                    processed_count += 1
            
            if processed_count == 0:
                st.warning("No valid geometries found in KML file. Trying alternative parsing...")
                # Try to extract coordinates directly
                self.extract_coordinates_directly(root)
            
            return len(self.geometries) > 0
            
        except Exception as e:
            st.error(f"Error parsing KML: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return False
    
    def extract_coordinates_directly(self, root):
        """Alternative method to extract coordinates directly"""
        # Find all coordinate elements
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
    
    def create_dxf(self, options):
        """Create DXF file from parsed geometries"""
        try:
            # Create new DXF document
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # Create all layers found
            for layer_name in self.stats['layers']:
                if layer_name and layer_name.strip():
                    try:
                        doc.layers.new(name=layer_name[:31])
                    except:
                        # If layer creation fails, use default
                        pass
            
            # Process each geometry
            for geom in self.geometries:
                geom_type = geom['type']
                coordinates = geom['coordinates']
                style = geom['style']
                
                layer_name = style['layer'][:31] if style['layer'] else '0'
                color = style['color']
                
                try:
                    if geom_type == 'POINT' and coordinates:
                        for x, y, z in coordinates:
                            msp.add_point(
                                (x, y, z),
                                dxfattribs={
                                    'layer': layer_name,
                                    'color': color
                                }
                            )
                    
                    elif geom_type == 'LINESTRING' and len(coordinates) >= 2:
                        if options['simplify_lines'] and len(coordinates) == 2:
                            # Simple line
                            msp.add_line(
                                coordinates[0],
                                coordinates[1],
                                dxfattribs={
                                    'layer': layer_name,
                                    'color': color,
                                    'lineweight': int(style['width'] * 100) if style['width'] > 0 else 0
                                }
                            )
                        else:
                            # Polyline
                            msp.add_polyline3d(
                                coordinates,
                                dxfattribs={
                                    'layer': layer_name,
                                    'color': color,
                                    'lineweight': int(style['width'] * 100) if style['width'] > 0 else 0
                                }
                            )
                    
                    elif geom_type in ['POLYGON', 'POLYGON_HOLE'] and len(coordinates) >= 3:
                        if options['create_hatch'] and geom_type == 'POLYGON':
                            try:
                                # Create hatch for filled polygon
                                hatch = msp.add_hatch(
                                    color=color,
                                    dxfattribs={'layer': layer_name}
                                )
                                # Convert 3D coordinates to 2D for hatch
                                coords_2d = [(x, y) for x, y, z in coordinates]
                                hatch.paths.add_polyline_path(
                                    coords_2d,
                                    is_closed=True
                                )
                            except:
                                # Fallback to polyline if hatch fails
                                msp.add_polyline3d(
                                    coordinates,
                                    dxfattribs={
                                        'layer': layer_name,
                                        'color': color
                                    }
                                )
                        else:
                            # Create polyline for polygon
                            msp.add_polyline3d(
                                coordinates,
                                dxfattribs={
                                    'layer': layer_name,
                                    'color': color
                                }
                            )
                
                except Exception as geom_error:
                    st.warning(f"Could not add geometry: {geom_error}")
                    continue
            
            # Save to BytesIO
            dxf_bytes = io.BytesIO()
            doc.saveas(dxf_bytes)
            dxf_bytes.seek(0)
            
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
            'Placemarks Processed': self.stats['total_placemarks'],
            'Points': self.stats['points'],
            'Lines': self.stats['lines'],
            'Polygons': self.stats['polygons'],
            'MultiGeometries': self.stats['multigeometries'],
            'Layers': len(self.stats['layers']),
            'Total Coordinates': sum(geom['count'] for geom in self.geometries)
        }

def main():
    # Header
    st.markdown('<h1 class="main-header">🗺️ KML to DXF Converter</h1>', unsafe_allow_html=True)
    st.markdown("Convert KML (Google Earth) files to DXF (CAD) format")
    
    # Initialize session state
    if 'converter' not in st.session_state:
        st.session_state.converter = None
    if 'conversion_done' not in st.session_state:
        st.session_state.conversion_done = False
    if 'dxf_bytes' not in st.session_state:
        st.session_state.dxf_bytes = None
    
    # Sidebar
    with st.sidebar:
        st.markdown("### ⚙️ Conversion Options")
        
        # Conversion options
        simplify_lines = st.checkbox("Simplify lines", value=True,
                                     help="Convert 2-point polylines to simple lines")
        create_hatch = st.checkbox("Create hatch for polygons", value=False,
                                   help="Create hatch patterns for filled polygons")
        force_3d = st.checkbox("Force 3D coordinates", value=False,
                              help="Keep Z coordinates even if zero")
        
        options = {
            'simplify_lines': simplify_lines,
            'create_hatch': create_hatch,
            'force_3d': force_3d
        }
        
        st.markdown("---")
        st.markdown("### 📊 Statistics")
        
        if st.session_state.converter and st.session_state.conversion_done:
            stats = st.session_state.converter.get_statistics()
            for key, value in stats.items():
                st.metric(key, value)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📤 Upload KML/KMZ File")
        
        uploaded_file = st.file_uploader(
            "Drag and drop or click to upload",
            type=['kml', 'kmz'],
            help="Supported formats: KML, KMZ (compressed KML)",
            key="file_uploader"
        )
        
        if uploaded_file is not None:
            # Display file info
            file_size = len(uploaded_file.getvalue()) / 1024  # KB
            st.info(f"**File:** {uploaded_file.name} | **Size:** {file_size:.1f} KB")
            
            # Read file content
            file_content = uploaded_file.getvalue()
            
            # Handle KMZ files
            if uploaded_file.name.lower().endswith('.kmz'):
                with st.spinner("Extracting KMZ file..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.kmz') as tmp:
                        tmp.write(file_content)
                        tmp_path = tmp.name
                    
                    try:
                        with zipfile.ZipFile(tmp_path, 'r') as kmz:
                            # Find the main KML file (usually doc.kml or the first .kml)
                            kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]
                            if kml_files:
                                # Prefer doc.kml
                                doc_kml = [f for f in kml_files if 'doc.kml' in f.lower()]
                                kml_file = doc_kml[0] if doc_kml else kml_files[0]
                                
                                with kmz.open(kml_file) as kml_file_obj:
                                    file_content = kml_file_obj.read()
                                st.success(f"Extracted: {kml_file}")
                            else:
                                st.error("No KML file found in KMZ archive")
                                return
                    except Exception as e:
                        st.error(f"Error extracting KMZ: {str(e)}")
                        return
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except:
                            pass
            
            # Parse and convert button
            if st.button("🚀 Convert to DXF", type="primary", use_container_width=True):
                with st.spinner("Processing KML file..."):
                    # Create converter instance
                    converter = KMLtoDXFConverter()
                    
                    # Parse KML
                    success = converter.parse_kml(file_content)
                    
                    if success:
                        st.session_state.converter = converter
                        
                        # Show statistics
                        stats = converter.get_statistics()
                        
                        col_stat1, col_stat2 = st.columns(2)
                        with col_stat1:
                            st.metric("Total Geometries", stats['Total Geometries'])
                            st.metric("Points", stats['Points'])
                            st.metric("Lines", stats['Lines'])
                        with col_stat2:
                            st.metric("Polygons", stats['Polygons'])
                            st.metric("Layers", stats['Layers'])
                            st.metric("Placemarks", stats['Placemarks Processed'])
                        
                        # Show layers
                        if converter.stats['layers']:
                            with st.expander("🏷️ Layers Found"):
                                layers_list = list(converter.stats['layers'])
                                for layer in sorted(layers_list)[:10]:  # Show first 10
                                    st.code(layer)
                                if len(layers_list) > 10:
                                    st.caption(f"... and {len(layers_list) - 10} more layers")
                        
                        # Create DXF
                        with st.spinner("Creating DXF file..."):
                            dxf_bytes = converter.create_dxf(options)
                            
                            if dxf_bytes:
                                st.session_state.dxf_bytes = dxf_bytes
                                st.session_state.conversion_done = True
                                st.success("✅ Conversion successful!")
                            else:
                                st.error("Failed to create DXF file")
                    else:
                        st.error("Failed to parse KML file")
            
            # Download section
            if st.session_state.conversion_done and st.session_state.dxf_bytes:
                st.markdown("---")
                st.markdown("### 📥 Download DXF File")
                
                # Generate filename
                if uploaded_file:
                    original_name = uploaded_file.name
                    base_name = os.path.splitext(original_name)[0]
                    dxf_filename = f"{base_name}_converted.dxf"
                else:
                    dxf_filename = f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
                
                # Download button
                st.download_button(
                    label="⬇️ Download DXF File",
                    data=st.session_state.dxf_bytes,
                    file_name=dxf_filename,
                    mime="application/dxf",
                    use_container_width=True
                )
                
                # File info
                file_size_mb = len(st.session_state.dxf_bytes.getvalue()) / (1024 * 1024)
                st.caption(f"File size: {file_size_mb:.2f} MB")
                
                # Preview coordinates
                if st.session_state.converter and st.session_state.converter.geometries:
                    with st.expander("📍 Coordinate Preview"):
                        preview_geom = st.session_state.converter.geometries[0]
                        if preview_geom['coordinates']:
                            first_coord = preview_geom['coordinates'][0]
                            st.code(f"Longitude: {first_coord[0]:.6f}\nLatitude: {first_coord[1]:.6f}\nElevation: {first_coord[2]:.1f}")
    
    with col2:
        st.markdown("### ℹ️ Quick Guide")
        
        st.markdown("""
        **1. Upload** your KML/KMZ file
        
        **2. Adjust** conversion options
        
        **3. Click** "Convert to DXF"
        
        **4. Download** the DXF file
        
        **Supported Elements:**
        - ✅ Points (Placemarks)
        - ✅ Lines (Paths)
        - ✅ Polygons (Areas)
        - ✅ Colors (Basic mapping)
        - ✅ Layers (From names)
        """)
        
        st.markdown("---")
        st.markdown("### 💡 Tips")
        
        st.markdown("""
        - **Large files** may take time
        - **Colors** are approximated
        - **KMZ** files auto-extract
        - **Check statistics** after upload
        - **Simplify lines** for cleaner output
        """)
        
        # Create sample KML
        st.markdown("---")
        st.markdown("### 🧪 Sample KML")
        
        sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Sample Map</name>
  <Placemark>
    <name>Jakarta</name>
    <Point>
      <coordinates>106.8456,-6.2088,0</coordinates>
    </Point>
  </Placemark>
  <Placemark>
    <name>Route</name>
    <LineString>
      <coordinates>
        106.8456,-6.2088,0
        106.8656,-6.2288,0
        106.8856,-6.2488,0
      </coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>Area</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            106.800,-6.150,0
            106.850,-6.150,0
            106.850,-6.200,0
            106.800,-6.200,0
            106.800,-6.150,0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>"""
        
        # Sample download
        st.download_button(
            label="Download Sample KML",
            data=sample_kml.encode(),
            file_name="sample_map.kml",
            mime="application/vnd.google-earth.kml+xml",
            use_container_width=True
        )

    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666;'>
        <p>KML to DXF Converter v2.1 | Built with Streamlit & ezdxf</p>
        <p>⚠️ Note: This tool converts geographic coordinates directly without projection transformation</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
