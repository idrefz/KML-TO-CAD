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
        
        # Clean up the coordinate string
        coord_text = coord_text.strip()
        lines = coord_text.split()
        
        for line in lines:
            # Handle commas and spaces
            parts = line.strip().split(',')
            if len(parts) >= 2:
                try:
                    # Longitude, Latitude, Elevation
                    lon = float(parts[0].strip())
                    lat = float(parts[1].strip())
                    
                    # Handle elevation if present
                    if len(parts) >= 3:
                        try:
                            elev = float(parts[2].strip())
                        except ValueError:
                            elev = 0.0
                    else:
                        elev = 0.0
                    
                    coords.append((lon, lat, elev))
                except ValueError as e:
                    # Skip invalid coordinates
                    continue
        
        return coords
    
    def kml_color_to_dxf(self, kml_color):
        """Convert KML color to DXF color index"""
        if not kml_color or not isinstance(kml_color, str):
            return 7  # White
        
        # Clean color string
        kml_color = kml_color.strip()
        if not kml_color.startswith('#'):
            return 7
        
        # KML: #aabbggrr (alpha, blue, green, red)
        color_hex = kml_color[1:]
        
        if len(color_hex) == 8:
            try:
                # Extract RGB components
                rr = int(color_hex[6:8], 16)  # Red
                gg = int(color_hex[4:6], 16)  # Green
                bb = int(color_hex[2:4], 16)  # Blue
                
                # Calculate brightness
                brightness = (rr + gg + bb) / 3
                
                # Map to DXF colors (1-7 are standard colors)
                if brightness < 30:
                    return 0    # Black
                elif brightness < 100:
                    return 8    # Dark Grey
                elif brightness < 150:
                    return 7    # White
                elif rr > max(gg, bb):
                    return 1    # Red
                elif gg > max(rr, bb):
                    return 3    # Green
                elif bb > max(rr, gg):
                    return 5    # Blue
                elif brightness > 200:
                    return 2    # Yellow
                else:
                    return 4    # Cyan
            except:
                return 7
        
        return 7
    
    def find_style_by_id(self, root, style_id):
        """Find style definition by ID in the XML tree"""
        # Search in entire document
        for elem in root.iter():
            # Check if this is a Style element
            if 'Style' in elem.tag:
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
            safe_name = name_elem.text.strip()
            # Clean layer name for DXF
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ' _-')
            style['layer'] = safe_name[:31] if safe_name else 'Layer_0'
            style['name'] = name_elem.text.strip()
        else:
            style['layer'] = 'Layer_0'
            style['name'] = 'Unnamed'
        
        # Try to get styleUrl
        style_url = placemark.find('.//{*}styleUrl')
        if style_url is not None and style_url.text:
            style_id = style_url.text.strip().replace('#', '')
            if style_id:
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
                                style['width'] = float(width_elem.text.strip())
                            except (ValueError, AttributeError):
                                style['width'] = 0.0
                    
                    # Polygon style
                    poly_style = style_def.find('.//{*}PolyStyle')
                    if poly_style is not None:
                        fill_elem = poly_style.find('.//{*}fill')
                        if fill_elem is not None and fill_elem.text:
                            style['filled'] = fill_elem.text.strip() == '1'
        
        return style
    
    def process_point(self, geometry_elem, style_info):
        """Process Point geometry"""
        coords_elem = geometry_elem.find('.//{*}coordinates')
        if coords_elem is not None and coords_elem.text:
            coordinates = self.parse_coordinates(coords_elem.text)
            if coordinates:
                for coord in coordinates:
                    self.geometries.append({
                        'type': 'POINT',
                        'coordinates': [coord],  # Single coordinate
                        'style': style_info,
                        'count': 1
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
                        
                        # Process inner boundaries (holes) if present
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
                processed = self.process_polygon(polygon_elem, style_info)  # FIXED: polygon_elem, not polygon
        
        # Check for MultiGeometry
        if not processed:
            multi_elem = placemark.find('.//{*}MultiGeometry')
            if multi_elem is not None:
                self.stats['multigeometries'] += 1
                # Process each geometry in MultiGeometry
                for geom_elem in multi_elem:
                    # Get tag without namespace
                    tag_parts = geom_elem.tag.split('}')
                    geom_type = tag_parts[-1] if len(tag_parts) > 1 else geom_elem.tag
                    
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
                if isinstance(kml_content, bytes):
                    kml_content = kml_content.decode('utf-8', errors='ignore')
                
                # Clean up the XML content
                kml_content = kml_content.replace('\x00', '')  # Remove null chars
                kml_content = kml_content.strip()
                
                root = ET.fromstring(kml_content)
            except ET.ParseError as e:
                st.warning(f"XML parsing error: {e}. Trying to fix XML...")
                # Try to fix common XML issues
                kml_content = kml_content.replace('&', '&amp;')
                root = ET.fromstring(kml_content)
            
            # Find all placemarks (handle multiple namespaces)
            placemarks = []
            
            # Try different namespace approaches
            namespaces_to_try = [
                'http://www.opengis.net/kml/2.2',
                'http://earth.google.com/kml/2.0',
                'http://earth.google.com/kml/2.1',
                'http://www.opengis.net/kml/2.1'
            ]
            
            for ns in namespaces_to_try:
                placemarks = root.findall(f'.//{{{ns}}}Placemark')
                if placemarks:
                    self.namespace['kml'] = ns
                    break
            
            if not placemarks:
                # Try without namespace
                placemarks = root.findall('.//Placemark')
            
            if not placemarks:
                # Try wildcard namespace
                placemarks = root.findall('.//{*}Placemark')
            
            self.stats['total_placemarks'] = len(placemarks)
            
            if not placemarks:
                st.warning("No placemarks found in KML file.")
                # Try to find any geometry directly
                return self.extract_geometries_directly(root)
            
            # Process each placemark
            processed_count = 0
            for placemark in placemarks:
                try:
                    if self.process_placemark(placemark, root):
                        processed_count += 1
                except Exception as e:
                    st.warning(f"Error processing placemark: {e}")
                    continue
            
            if processed_count == 0:
                st.warning("No valid geometries found in placemarks. Trying direct extraction...")
                return self.extract_geometries_directly(root)
            
            return len(self.geometries) > 0
            
        except Exception as e:
            st.error(f"Error parsing KML: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return False
    
    def extract_geometries_directly(self, root):
        """Alternative method to extract coordinates directly"""
        try:
            # Find all coordinate elements
            coord_elems = root.findall('.//{*}coordinates')
            
            for elem in coord_elems:
                if elem.text:
                    coordinates = self.parse_coordinates(elem.text)
                    if coordinates:
                        # Determine geometry type based on number of coordinates
                        if len(coordinates) == 1:
                            self.geometries.append({
                                'type': 'POINT',
                                'coordinates': coordinates,
                                'style': {
                                    'color': 7, 
                                    'layer': 'Extracted', 
                                    'name': 'Point',
                                    'width': 0.0,
                                    'filled': True
                                },
                                'count': 1
                            })
                            self.stats['points'] += 1
                            self.stats['layers'].add('Extracted')
                        elif len(coordinates) == 2:
                            self.geometries.append({
                                'type': 'LINESTRING',
                                'coordinates': coordinates,
                                'style': {
                                    'color': 7, 
                                    'layer': 'Extracted', 
                                    'name': 'Line',
                                    'width': 0.0,
                                    'filled': True
                                },
                                'count': 2
                            })
                            self.stats['lines'] += 1
                            self.stats['layers'].add('Extracted')
                        elif len(coordinates) >= 3:
                            self.geometries.append({
                                'type': 'POLYGON',
                                'coordinates': coordinates,
                                'style': {
                                    'color': 7, 
                                    'layer': 'Extracted', 
                                    'name': 'Polygon',
                                    'width': 0.0,
                                    'filled': True
                                },
                                'count': len(coordinates)
                            })
                            self.stats['polygons'] += 1
                            self.stats['layers'].add('Extracted')
            
            return len(self.geometries) > 0
            
        except Exception as e:
            st.error(f"Error in direct extraction: {e}")
            return False
    
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
                        # DXF layer names are limited to 31 characters
                        safe_layer_name = layer_name[:31].strip()
                        if safe_layer_name:
                            doc.layers.new(name=safe_layer_name)
                    except Exception as e:
                        st.warning(f"Could not create layer '{layer_name}': {e}")
            
            # Process each geometry
            for geom in self.geometries:
                geom_type = geom['type']
                coordinates = geom['coordinates']
                style = geom['style']
                
                layer_name = style['layer'][:31].strip() if style['layer'] else '0'
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
                        if options['create_hatch'] and geom_type == 'POLYGON' and style.get('filled', True):
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
                            except Exception as hatch_error:
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
                    # Skip this geometry but continue with others
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
            'Placemarks Found': self.stats['total_placemarks'],
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
        preserve_layers = st.checkbox("Preserve layers", value=True,
                                     help="Create separate layers for different elements")
        
        options = {
            'simplify_lines': simplify_lines,
            'create_hatch': create_hatch,
            'preserve_layers': preserve_layers
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
            file_type = uploaded_file.type if uploaded_file.type else "Unknown"
            st.info(f"**File:** {uploaded_file.name} | **Size:** {file_size:.1f} KB | **Type:** {file_type}")
            
            # Read file content
            file_content = uploaded_file.getvalue()
            
            # Handle KMZ files
            if uploaded_file.name.lower().endswith('.kmz'):
                with st.spinner("Extracting KMZ file..."):
                    try:
                        with zipfile.ZipFile(io.BytesIO(file_content), 'r') as kmz:
                            # Find KML files in the archive
                            kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]
                            
                            if kml_files:
                                # Sort to prefer doc.kml
                                kml_files.sort(key=lambda x: 'doc.kml' in x.lower(), reverse=True)
                                kml_file = kml_files[0]
                                
                                with kmz.open(kml_file) as kml_file_obj:
                                    file_content = kml_file_obj.read()
                                st.success(f"✅ Extracted: {kml_file}")
                            else:
                                st.error("❌ No KML file found in KMZ archive")
                                return
                    except Exception as e:
                        st.error(f"❌ Error extracting KMZ: {str(e)}")
                        return
            
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
                        
                        st.success(f"✅ Successfully parsed {stats['Total Geometries']} geometries")
                        
                        # Display statistics in columns
                        col_stat1, col_stat2 = st.columns(2)
                        with col_stat1:
                            st.metric("Total Geometries", stats['Total Geometries'])
                            st.metric("Points", stats['Points'])
                            st.metric("Lines", stats['Lines'])
                        with col_stat2:
                            st.metric("Polygons", stats['Polygons'])
                            st.metric("Layers", stats['Layers'])
                            st.metric("Placemarks", stats['Placemarks Found'])
                        
                        # Show layers
                        if converter.stats['layers']:
                            with st.expander("🏷️ Layers Found", expanded=False):
                                layers_list = list(converter.stats['layers'])
                                for layer in sorted(layers_list)[:15]:  # Show first 15
                                    st.code(layer)
                                if len(layers_list) > 15:
                                    st.caption(f"... and {len(layers_list) - 15} more layers")
                        
                        # Create DXF
                        with st.spinner("Creating DXF file..."):
                            dxf_bytes = converter.create_dxf(options)
                            
                            if dxf_bytes:
                                st.session_state.dxf_bytes = dxf_bytes
                                st.session_state.conversion_done = True
                                st.success("✅ DXF file created successfully!")
                            else:
                                st.error("❌ Failed to create DXF file")
                    else:
                        st.error("❌ Failed to parse KML file. The file might be corrupted or in an unsupported format.")
            
            # Download section
            if st.session_state.conversion_done and st.session_state.dxf_bytes:
                st.markdown("---")
                st.markdown("### 📥 Download DXF File")
                
                # Generate filename
                if uploaded_file:
                    original_name = uploaded_file.name
                    base_name = os.path.splitext(original_name)[0]
                    # Remove .kmz if present
                    if base_name.lower().endswith('.kmz'):
                        base_name = base_name[:-4]
                    dxf_filename = f"{base_name}_converted.dxf"
                else:
                    dxf_filename = f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
                
                # Download button
                st.download_button(
                    label="⬇️ Download DXF File",
                    data=st.session_state.dxf_bytes,
                    file_name=dxf_filename,
                    mime="application/dxf",
                    use_container_width=True,
                    help="Click to download the converted DXF file"
                )
                
                # File info
                file_size_mb = len(st.session_state.dxf_bytes.getvalue()) / (1024 * 1024)
                st.caption(f"📏 File size: {file_size_mb:.2f} MB")
                
                # Preview coordinates
                if st.session_state.converter and st.session_state.converter.geometries:
                    with st.expander("📍 Coordinate Preview", expanded=False):
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
        - ✅ Lines (Paths/Routes)
        - ✅ Polygons (Areas/Regions)
        - ✅ Basic color mapping
        - ✅ Layer preservation
        - ✅ KMZ file support
        """)
        
        st.markdown("---")
        st.markdown("### 💡 Tips")
        
        st.markdown("""
        - **Large files** may take longer to process
        - **Colors** are approximated to DXF color palette
        - **KMZ** files are automatically extracted
        - **Check statistics** after upload
        - **Simplify lines** option reduces file size
        - Use **hatch** for filled polygons
        """)
        
        # Create sample KML
        st.markdown("---")
        st.markdown("### 🧪 Try Sample KML")
        
        sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Sample Map Data</name>
  
  <Placemark>
    <name>City Center</name>
    <description>Main city point</description>
    <Point>
      <coordinates>106.845599,-6.208763,0</coordinates>
    </Point>
  </Placemark>
  
  <Placemark>
    <name>Main Road</name>
    <LineString>
      <coordinates>
        106.845599,-6.208763,0
        106.855599,-6.218763,0
        106.865599,-6.228763,0
      </coordinates>
    </LineString>
  </Placemark>
  
  <Placemark>
    <name>Park Area</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            106.830000,-6.190000,0
            106.840000,-6.190000,0
            106.840000,-6.200000,0
            106.830000,-6.200000,0
            106.830000,-6.190000,0
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
            data=sample_kml.encode('utf-8'),
            file_name="sample_map.kml",
            mime="application/vnd.google-earth.kml+xml",
            use_container_width=True,
            help="Download a sample KML file to test the converter"
        )
        
        st.markdown("---")
        st.markdown("### 🔧 Technical Info")
        
        st.markdown("""
        **Output Format:** DXF R2010
        **Coordinate System:** Geographic (WGS84)
        **Limitations:**
        - No coordinate transformation
        - Basic color support
        - 2D/3D mixed support
        """)

    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666; padding: 1rem;'>
        <p><strong>KML to DXF Converter v2.2</strong> | Built with Streamlit & ezdxf</p>
        <p style='font-size: 0.9rem;'>⚠️ Note: Geographic coordinates are converted directly without projection transformation.</p>
        <p style='font-size: 0.8rem;'>For accurate CAD drawings, consider applying appropriate coordinate transformations.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
