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
            'layers': set()
        }
    
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
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2]) if len(parts) >= 3 else 0.0
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
            rr = int(color_hex[6:8], 16)
            gg = int(color_hex[4:6], 16)
            bb = int(color_hex[2:4], 16)
            brightness = (rr + gg + bb) / 3
            
            # Map brightness to DXF color index (1-7)
            if brightness < 50:
                return 0  # Black
            elif brightness < 100:
                return 8  # Dark Grey
            elif brightness < 150:
                return 7  # White
            elif brightness < 200:
                return 1  # Red
            else:
                return 2  # Yellow
        
        return 7
    
    def extract_style_info(self, placemark):
        """Extract style information from placemark"""
        style = {
            'color': 7,  # Default white
            'width': 0.0,
            'layer': 'Default',
            'filled': True
        }
        
        # Get name for layer
        name_elem = placemark.find('.//kml:name', self.namespace)
        if name_elem is not None and name_elem.text:
            style['layer'] = name_elem.text[:31]  # DXF layer name limit
        
        # Try to get styleUrl
        style_url = placemark.find('.//kml:styleUrl', self.namespace)
        if style_url is not None and style_url.text:
            style_id = style_url.text.replace('#', '')
            
            # Find style definition
            root = placemark.getroot()
            style_def = root.find(f".//kml:Style[@id='{style_id}']", self.namespace)
            
            if style_def is None:
                # Check in Document or Folder
                for parent in placemark.iterfind('..'):
                    style_def = parent.find(f".//kml:Style[@id='{style_id}']", self.namespace)
                    if style_def is not None:
                        break
            
            if style_def is not None:
                # Line style
                line_style = style_def.find('.//kml:LineStyle', self.namespace)
                if line_style is not None:
                    color_elem = line_style.find('.//kml:color', self.namespace)
                    if color_elem is not None:
                        style['color'] = self.kml_color_to_dxf(color_elem.text)
                    
                    width_elem = line_style.find('.//kml:width', self.namespace)
                    if width_elem is not None:
                        try:
                            style['width'] = float(width_elem.text)
                        except ValueError:
                            style['width'] = 0.0
                
                # Polygon style
                poly_style = style_def.find('.//kml:PolyStyle', self.namespace)
                if poly_style is not None:
                    fill_elem = poly_style.find('.//kml:fill', self.namespace)
                    if fill_elem is not None:
                        style['filled'] = fill_elem.text == '1'
        
        return style
    
    def process_placemark(self, placemark):
        """Process a single placemark and return geometries"""
        geometries = []
        style = self.extract_style_info(placemark)
        
        # Track layer
        self.stats['layers'].add(style['layer'])
        
        # Check for different geometry types
        geometry_elements = [
            ('Point', './/kml:Point'),
            ('LineString', './/kml:LineString'),
            ('Polygon', './/kml:Polygon')
        ]
        
        for geom_type, xpath in geometry_elements:
            geom_elem = placemark.find(xpath, self.namespace)
            if geom_elem is not None:
                coords_elem = geom_elem.find('.//kml:coordinates', self.namespace)
                if coords_elem is not None and coords_elem.text:
                    coordinates = self.parse_coordinates(coords_elem.text)
                    
                    if geom_type == 'Polygon' and coordinates:
                        # Handle polygon outer boundary
                        outer_boundary = geom_elem.find('.//kml:outerBoundaryIs', self.namespace)
                        if outer_boundary is not None:
                            ring = outer_boundary.find('.//kml:LinearRing', self.namespace)
                            if ring is not None:
                                coords_elem = ring.find('.//kml:coordinates', self.namespace)
                                if coords_elem is not None:
                                    coordinates = self.parse_coordinates(coords_elem.text)
                    
                    if coordinates:
                        geometries.append({
                            'type': geom_type,
                            'coordinates': coordinates,
                            'style': style.copy(),
                            'name': style['layer']
                        })
                        
                        # Update statistics
                        if geom_type == 'Point':
                            self.stats['points'] += 1
                        elif geom_type == 'LineString':
                            self.stats['lines'] += 1
                        elif geom_type == 'Polygon':
                            self.stats['polygons'] += 1
        
        # Check for MultiGeometry
        multi_geom = placemark.find('.//kml:MultiGeometry', self.namespace)
        if multi_geom is not None:
            for geom_elem in multi_geom:
                geom_type = geom_elem.tag.split('}')[-1]
                coords_elem = geom_elem.find('.//kml:coordinates', self.namespace)
                
                if geom_type == 'Polygon' and coords_elem is None:
                    # Handle polygon in MultiGeometry
                    outer_boundary = geom_elem.find('.//kml:outerBoundaryIs', self.namespace)
                    if outer_boundary is not None:
                        ring = outer_boundary.find('.//kml:LinearRing', self.namespace)
                        if ring is not None:
                            coords_elem = ring.find('.//kml:coordinates', self.namespace)
                
                if coords_elem is not None and coords_elem.text:
                    coordinates = self.parse_coordinates(coords_elem.text)
                    if coordinates:
                        geometries.append({
                            'type': geom_type,
                            'coordinates': coordinates,
                            'style': style.copy(),
                            'name': style['layer']
                        })
                        
                        # Update statistics
                        if geom_type == 'Point':
                            self.stats['points'] += 1
                        elif geom_type == 'LineString':
                            self.stats['lines'] += 1
                        elif geom_type == 'Polygon':
                            self.stats['polygons'] += 1
        
        return geometries
    
    def parse_kml(self, kml_content):
        """Parse KML content"""
        try:
            # Try to parse as XML
            root = ET.fromstring(kml_content)
            
            # Register namespace
            for elem in root.iter():
                if '}' in elem.tag:
                    ns = elem.tag.split('}')[0].strip('{')
                    self.namespace['kml'] = ns
                    break
            
            # Find all placemarks
            placemarks = root.findall('.//kml:Placemark', self.namespace)
            
            if not placemarks:
                # Try common namespaces
                for ns in ['http://earth.google.com/kml/2.0',
                          'http://earth.google.com/kml/2.1',
                          'http://www.opengis.net/kml/2.1']:
                    self.namespace['kml'] = ns
                    placemarks = root.findall('.//kml:Placemark', self.namespace)
                    if placemarks:
                        break
            
            self.stats['total_placemarks'] = len(placemarks)
            
            all_geometries = []
            for placemark in placemarks:
                geometries = self.process_placemark(placemark)
                all_geometries.extend(geometries)
            
            return all_geometries
            
        except ET.ParseError as e:
            st.error(f"Error parsing KML file: {str(e)}")
            return None
        except Exception as e:
            st.error(f"Error processing KML: {str(e)}")
            return None
    
    def create_dxf(self, geometries, options):
        """Create DXF file from geometries"""
        try:
            # Create new DXF document
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # Create layers
            for layer_name in self.stats['layers']:
                doc.layers.new(name=layer_name)
            
            # Process each geometry
            for geom in geometries:
                layer_name = geom['style']['layer']
                color = geom['style']['color']
                
                if geom['type'] == 'Point' and geom['coordinates']:
                    for x, y, z in geom['coordinates']:
                        msp.add_point((x, y, z), 
                                     dxfattribs={'layer': layer_name, 'color': color})
                
                elif geom['type'] == 'LineString' and len(geom['coordinates']) >= 2:
                    if options['simplify_lines'] and len(geom['coordinates']) == 2:
                        msp.add_line(geom['coordinates'][0], geom['coordinates'][1],
                                    dxfattribs={'layer': layer_name, 'color': color})
                    else:
                        msp.add_polyline3d(geom['coordinates'],
                                          dxfattribs={'layer': layer_name, 'color': color})
                
                elif geom['type'] == 'Polygon' and len(geom['coordinates']) >= 3:
                    coords = geom['coordinates']
                    # Close polygon if not closed
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    
                    if options['create_hatch'] and len(coords) >= 3:
                        try:
                            # Try to create hatch for polygon
                            hatch = msp.add_hatch(color=color, dxfattribs={'layer': layer_name})
                            hatch.paths.add_polyline_path(coords, is_closed=True)
                        except:
                            # Fallback to polyline if hatch fails
                            msp.add_polyline3d(coords, dxfattribs={'layer': layer_name, 'color': color})
                    else:
                        msp.add_polyline3d(coords, dxfattribs={'layer': layer_name, 'color': color})
            
            # Save to BytesIO
            dxf_bytes = io.BytesIO()
            doc.saveas(dxf_bytes)
            dxf_bytes.seek(0)
            
            return dxf_bytes
            
        except Exception as e:
            st.error(f"Error creating DXF: {str(e)}")
            return None

def get_file_download_link(file_bytes, filename, file_format):
    """Generate a download link for the file"""
    b64 = base64.b64encode(file_bytes.getvalue()).decode()
    return f'<a href="data:application/{file_format};base64,{b64}" download="{filename}">Download {filename}</a>'

def main():
    # Header
    st.markdown('<h1 class="main-header">🗺️ KML to DXF Converter</h1>', unsafe_allow_html=True)
    st.markdown("Convert KML (Google Earth) files to DXF (CAD) format")
    
    # Sidebar
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2917/2917995.png", width=100)
        st.markdown("### 📋 About")
        st.markdown("""
        This tool converts KML files from Google Earth 
        to DXF format for use in CAD software.
        
        **Supported formats:**
        - KML (Keyhole Markup Language)
        - Output: DXF R2010
        
        **Features:**
        - Point conversion
        - LineString conversion  
        - Polygon conversion
        - Layer preservation
        - Color mapping
        """)
        
        st.markdown("---")
        st.markdown("### ⚙️ Conversion Options")
        
        # Conversion options
        simplify_lines = st.checkbox("Simplify lines", value=True, 
                                     help="Convert polylines with 2 points to simple lines")
        create_hatch = st.checkbox("Create hatch for polygons", value=False,
                                   help="Create hatch patterns for polygons (experimental)")
        preserve_colors = st.checkbox("Preserve colors", value=True,
                                      help="Try to preserve KML colors in DXF")
        
        options = {
            'simplify_lines': simplify_lines,
            'create_hatch': create_hatch,
            'preserve_colors': preserve_colors
        }
        
        st.markdown("---")
        st.markdown("### 📊 Statistics")
        if 'converter' in st.session_state:
            stats = st.session_state.converter.stats
            st.metric("Placemarks", stats['total_placemarks'])
            st.metric("Points", stats['points'])
            st.metric("Lines", stats['lines'])
            st.metric("Polygons", stats['polygons'])
            st.metric("Layers", len(stats['layers']))
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📤 Upload KML File")
        
        uploaded_file = st.file_uploader(
            "Choose a KML file",
            type=['kml', 'kmz'],
            help="Upload KML or KMZ file from Google Earth"
        )
        
        if uploaded_file is not None:
            # Read file content
            file_content = uploaded_file.read()
            
            # Handle KMZ files (zipped KML)
            if uploaded_file.name.lower().endswith('.kmz'):
                with tempfile.NamedTemporaryFile(delete=False, suffix='.kmz') as tmp:
                    tmp.write(file_content)
                    tmp_path = tmp.name
                
                try:
                    with zipfile.ZipFile(tmp_path, 'r') as kmz:
                        # Find the main KML file
                        kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                        if kml_files:
                            with kmz.open(kml_files[0]) as kml_file:
                                file_content = kml_file.read()
                        else:
                            st.error("No KML file found in KMZ archive")
                            return
                except Exception as e:
                    st.error(f"Error extracting KMZ file: {str(e)}")
                    return
                finally:
                    os.unlink(tmp_path)
            
            # Parse and convert
            with st.spinner("Processing KML file..."):
                converter = KMLtoDXFConverter()
                st.session_state.converter = converter
                
                geometries = converter.parse_kml(file_content)
                
                if geometries:
                    st.success(f"✅ Successfully parsed {len(geometries)} geometries")
                    
                    # Display preview
                    with st.expander("📊 File Statistics", expanded=True):
                        col_stat1, col_stat2, col_stat3 = st.columns(3)
                        with col_stat1:
                            st.metric("Total Geometries", len(geometries))
                            st.metric("Layers", len(converter.stats['layers']))
                        with col_stat2:
                            st.metric("Points", converter.stats['points'])
                            st.metric("Lines", converter.stats['lines'])
                        with col_stat3:
                            st.metric("Polygons", converter.stats['polygons'])
                            st.metric("Placemarks", converter.stats['total_placemarks'])
                    
                    # Display layers
                    if converter.stats['layers']:
                        with st.expander("🏷️ Layers Found"):
                            for layer in sorted(converter.stats['layers']):
                                st.code(layer)
                    
                    # Convert to DXF
                    with st.spinner("Creating DXF file..."):
                        dxf_bytes = converter.create_dxf(geometries, options)
                        
                        if dxf_bytes:
                            # Generate filename
                            original_name = uploaded_file.name
                            base_name = os.path.splitext(original_name)[0]
                            dxf_filename = f"{base_name}_converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
                            
                            # Download button
                            st.markdown("### 📥 Download DXF File")
                            st.download_button(
                                label="Download DXF",
                                data=dxf_bytes,
                                file_name=dxf_filename,
                                mime="application/dxf"
                            )
                            
                            # Preview info
                            st.markdown("""
                            ### ✅ Conversion Complete!
                            
                            **Next steps:**
                            1. Download the DXF file using the button above
                            2. Open in your CAD software (AutoCAD, DraftSight, etc.)
                            3. Verify the conversion results
                            
                            **Tips:**
                            - Layers are preserved from KML names
                            - Colors are mapped where possible
                            - Coordinates are in geographic format (longitude, latitude)
                            """)
                else:
                    st.error("No geometries found in the KML file")
    
    with col2:
        st.markdown("### ℹ️ How to Use")
        
        st.markdown("""
        **Step-by-step:**
        
        1. **Upload KML**  
           Drag & drop or click to upload
        
        2. **Adjust Settings**  
           Use sidebar options
        
        3. **Convert**  
           Automatic conversion
        
        4. **Download**  
           Get your DXF file
        
        **Example KML Sources:**
        - Google Earth
        - Google My Maps
        - GPS devices
        - GIS software
        """)
        
        st.markdown("---")
        st.markdown("### 💡 Tips")
        
        st.markdown("""
        - **Large files** may take longer to process
        - **Complex polygons** might need adjustment
        - **Colors** are approximated for DXF
        - **KMZ files** are automatically extracted
        - Check **statistics** in sidebar
        """)
        
        # Sample KML file
        st.markdown("---")
        st.markdown("### 🧪 Try Sample")
        
        sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Sample KML</name>
  <Placemark>
    <name>Point 1</name>
    <Point>
      <coordinates>107.608, -6.891, 0</coordinates>
    </Point>
  </Placemark>
  <Placemark>
    <name>Line 1</name>
    <LineString>
      <coordinates>107.610, -6.892, 0 107.615, -6.895, 0</coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>Polygon 1</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            107.600, -6.900, 0
            107.605, -6.900, 0
            107.605, -6.895, 0
            107.600, -6.895, 0
            107.600, -6.900, 0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>"""
        
        # Create download for sample
        sample_bytes = io.BytesIO(sample_kml.encode())
        
        st.download_button(
            label="Download Sample KML",
            data=sample_bytes,
            file_name="sample_kml.kml",
            mime="application/vnd.google-earth.kml+xml"
        )

    # Footer
    st.markdown("---")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        st.markdown("**Version:** 2.0.0")
    with col_f2:
        st.markdown("**Format:** KML/KMZ to DXF")
    with col_f3:
        st.markdown("**Powered by:** Streamlit + ezdxf")

if __name__ == "__main__":
    main()
