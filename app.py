import streamlit as st
import xml.etree.ElementTree as ET
import ezdxf
from ezdxf import units
import io
import zipfile
import os
from datetime import datetime

# Set page configuration
st.set_page_config(
    page_title="KML to DXF Converter",
    page_icon="🗺️",
    layout="wide"
)

# Title
st.title("🗺️ KML to DXF Converter")
st.markdown("Convert Google Earth KML/KMZ files to DXF format for CAD software")

class SimpleKMLtoDXF:
    def __init__(self):
        self.geometries = []
        self.stats = {
            'points': 0,
            'lines': 0,
            'polygons': 0,
            'total': 0
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
    
    def extract_placemarks(self, root):
        """Extract placemarks from KML"""
        placemarks = []
        
        # Try different namespace approaches
        namespaces = [
            '{http://www.opengis.net/kml/2.2}',
            '{http://earth.google.com/kml/2.0}',
            '{http://earth.google.com/kml/2.1}',
            '{http://www.opengis.net/kml/2.1}',
            ''
        ]
        
        for ns in namespaces:
            placemarks = root.findall(f'.//{ns}Placemark')
            if placemarks:
                break
        
        return placemarks
    
    def process_kml_content(self, kml_content):
        """Process KML content"""
        try:
            # Parse XML
            root = ET.fromstring(kml_content)
            
            # Get placemarks
            placemarks = self.extract_placemarks(root)
            
            for pm in placemarks:
                # Get name
                name_elem = pm.find('.//{*}name')
                name = name_elem.text if name_elem is not None and name_elem.text else 'Unnamed'
                
                # Process Point
                point = pm.find('.//{*}Point')
                if point is not None:
                    coords_elem = point.find('.//{*}coordinates')
                    if coords_elem is not None and coords_elem.text:
                        coords = self.parse_coordinates(coords_elem.text)
                        if coords:
                            self.geometries.append({
                                'type': 'POINT',
                                'name': name,
                                'coords': coords
                            })
                            self.stats['points'] += len(coords)
                
                # Process LineString
                line = pm.find('.//{*}LineString')
                if line is not None:
                    coords_elem = line.find('.//{*}coordinates')
                    if coords_elem is not None and coords_elem.text:
                        coords = self.parse_coordinates(coords_elem.text)
                        if len(coords) >= 2:
                            self.geometries.append({
                                'type': 'LINE',
                                'name': name,
                                'coords': coords
                            })
                            self.stats['lines'] += 1
                
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
                                    self.geometries.append({
                                        'type': 'POLYGON',
                                        'name': name,
                                        'coords': coords
                                    })
                                    self.stats['polygons'] += 1
            
            self.stats['total'] = len(self.geometries)
            return True
            
        except Exception as e:
            st.error(f"Error processing KML: {e}")
            return False
    
    def create_dxf_file(self):
        """Create DXF file from geometries"""
        try:
            # Create a new DXF document
            doc = ezdxf.new('R2010', setup=True)
            doc.units = units.M
    
            # Setup modelspace
            msp = doc.modelspace()
            
            # Scale factor for geographic coordinates
            scale = 100000  # Scale up for better visibility
            
            # Colors for different geometry types
            colors = {
                'POINT': 1,    # Red
                'LINE': 3,     # Green
                'POLYGON': 5   # Blue
            }
            
            entities_added = 0
            
            # Add all geometries
            for geom in self.geometries:
                geom_type = geom['type']
                coords = geom['coords']
                name = geom['name'][:30]  # Truncate for layer name
                
                # Create layer
                try:
                    doc.layers.new(name=name)
                except:
                    # Layer might already exist
                    pass
                
                color = colors.get(geom_type, 7)
                
                if geom_type == 'POINT':
                    for lon, lat, elev in coords:
                        # Scale coordinates
                        x = lon * scale
                        y = lat * scale
                        z = elev
                        
                        msp.add_point((x, y, z), dxfattribs={
                            'layer': name,
                            'color': color
                        })
                        entities_added += 1
                
                elif geom_type == 'LINE':
                    if len(coords) >= 2:
                        # Scale all coordinates
                        scaled_coords = []
                        for lon, lat, elev in coords:
                            x = lon * scale
                            y = lat * scale
                            z = elev
                            scaled_coords.append((x, y, z))
                        
                        # Add as polyline
                        msp.add_polyline3d(scaled_coords, dxfattribs={
                            'layer': name,
                            'color': color
                        })
                        entities_added += 1
                
                elif geom_type == 'POLYGON':
                    if len(coords) >= 3:
                        # Scale all coordinates
                        scaled_coords = []
                        for lon, lat, elev in coords:
                            x = lon * scale
                            y = lat * scale
                            z = elev
                            scaled_coords.append((x, y, z))
                        
                        # Add as closed polyline
                        msp.add_polyline3d(scaled_coords, dxfattribs={
                            'layer': name,
                            'color': color
                        })
                        entities_added += 1
            
            # If no geometries were added, add a simple test entity
            if entities_added == 0:
                st.warning("No geometries found. Adding test entities...")
                
                # Add some test geometries
                msp.add_point((0, 0, 0), dxfattribs={'layer': 'Test', 'color': 1})
                msp.add_line((0, 0, 0), (10, 10, 0), dxfattribs={'layer': 'Test', 'color': 3})
                msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], 
                                  dxfattribs={'layer': 'Test', 'color': 5, 'closed': True})
                entities_added = 3
            
            # Save to bytes
            dxf_bytes = io.BytesIO()
            doc.saveas(dxf_bytes)
            dxf_bytes.seek(0)
            
            # Verify file is not empty
            file_size = len(dxf_bytes.getvalue())
            if file_size == 0:
                raise ValueError("Generated DXF file is empty")
            
            st.success(f"Created DXF with {entities_added} entities ({file_size:,} bytes)")
            return dxf_bytes
            
        except Exception as e:
            st.error(f"Error creating DXF: {e}")
            # Create minimal DXF as fallback
            return self.create_minimal_dxf()
    
    def create_minimal_dxf(self):
        """Create a minimal valid DXF file"""
        try:
            # Create simplest possible DXF
            doc = ezdxf.new('R12')
            msp = doc.modelspace()
            
            # Add a single point to ensure file is not empty
            msp.add_point((0, 0, 0))
            
            # Save
            dxf_bytes = io.BytesIO()
            doc.saveas(dxf_bytes)
            dxf_bytes.seek(0)
            
            st.info("Created minimal DXF file")
            return dxf_bytes
            
        except Exception as e:
            st.error(f"Even minimal DXF failed: {e}")
            # Create raw DXF text as last resort
            return self.create_raw_dxf()
    
    def create_raw_dxf(self):
        """Create raw DXF ASCII as last resort"""
        # Minimal DXF R12 format with a single point
        dxf_text = """  0
SECTION
  2
HEADER
  9
$ACADVER
  1
AC1009
  0
ENDSEC
  0
SECTION
  2
TABLES
  0
TABLE
  2
LAYER
  70
     1
  0
LAYER
  2
0
  70
     0
  62
     7
  6
CONTINUOUS
  0
ENDTAB
  0
ENDSEC
  0
SECTION
  2
ENTITIES
  0
POINT
  8
0
 10
0.0
 20
0.0
 30
0.0
  0
ENDSEC
  0
EOF
"""
        return io.BytesIO(dxf_text.encode('utf-8'))

# Initialize session state
if 'converter' not in st.session_state:
    st.session_state.converter = None
if 'dxf_ready' not in st.session_state:
    st.session_state.dxf_ready = False
if 'dxf_bytes' not in st.session_state:
    st.session_state.dxf_bytes = None

# Sidebar for options
with st.sidebar:
    st.header("⚙️ Settings")
    
    scale_factor = st.slider(
        "Coordinate Scale",
        min_value=1000,
        max_value=1000000,
        value=100000,
        step=1000,
        help="Scale geographic coordinates for better visibility in CAD"
    )
    
    st.markdown("---")
    st.header("ℹ️ Info")
    st.markdown("""
    **Supported:**
    - Points
    - Lines/Paths  
    - Polygons
    - Basic styling
    
    **Output:** DXF R2010
    """)

# Main area
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📤 Upload KML/KMZ File")
    
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=['kml', 'kmz'],
        help="Upload KML or KMZ file from Google Earth"
    )
    
    if uploaded_file is not None:
        # Show file info
        file_size = len(uploaded_file.getvalue())
        st.info(f"📄 **File:** {uploaded_file.name} ({file_size:,} bytes)")
        
        # Read file
        file_content = uploaded_file.getvalue()
        
        # Handle KMZ
        if uploaded_file.name.lower().endswith('.kmz'):
            try:
                with zipfile.ZipFile(io.BytesIO(file_content)) as kmz:
                    kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]
                    if kml_files:
                        kml_files.sort()
                        with kmz.open(kml_files[0]) as f:
                            file_content = f.read()
                        st.success(f"📂 Extracted: {kml_files[0]}")
                    else:
                        st.error("No KML file found in KMZ")
            except Exception as e:
                st.error(f"KMZ error: {e}")
        
        # Convert button
        if st.button("🚀 Convert to DXF", type="primary", use_container_width=True):
            with st.spinner("Processing..."):
                # Create converter
                converter = SimpleKMLtoDXF()
                
                # Process KML
                if converter.process_kml_content(file_content):
                    st.session_state.converter = converter
                    
                    # Show stats
                    stats = converter.stats
                    st.success(f"✅ Found {stats['total']} geometries")
                    
                    # Display stats
                    cols = st.columns(3)
                    cols[0].metric("Points", stats['points'])
                    cols[1].metric("Lines", stats['lines'])
                    cols[2].metric("Polygons", stats['polygons'])
                    
                    # Create DXF
                    with st.spinner("Creating DXF..."):
                        dxf_bytes = converter.create_dxf_file()
                        
                        if dxf_bytes:
                            st.session_state.dxf_bytes = dxf_bytes
                            st.session_state.dxf_ready = True
                            
                            # Show file size
                            file_size = len(dxf_bytes.getvalue())
                            st.success(f"✅ DXF ready: {file_size:,} bytes")
                        else:
                            st.error("Failed to create DXF")
                else:
                    st.error("Failed to process KML")

with col2:
    st.subheader("📥 Download")
    
    if st.session_state.dxf_ready and st.session_state.dxf_bytes:
        # Generate filename
        if uploaded_file:
            base = os.path.splitext(uploaded_file.name)[0]
            if base.lower().endswith('.kmz'):
                base = base[:-4]
            filename = f"{base}.dxf"
        else:
            filename = f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
        
        # Download button
        file_size = len(st.session_state.dxf_bytes.getvalue())
        st.download_button(
            label=f"⬇️ Download DXF ({file_size:,} bytes)",
            data=st.session_state.dxf_bytes,
            file_name=filename,
            mime="application/dxf",
            use_container_width=True
        )
        
        # Preview
        with st.expander("🔍 Preview Details"):
            if st.session_state.converter:
                converter = st.session_state.converter
                st.write(f"**Total Geometries:** {converter.stats['total']}")
                
                if converter.geometries:
                    # Show first few geometries
                    st.write("**Sample Geometries:**")
                    for i, geom in enumerate(converter.geometries[:3]):
                        st.write(f"{i+1}. {geom['type']}: {geom['name']}")
                        if geom['coords']:
                            coord = geom['coords'][0]
                            st.code(f"  Coordinate: {coord[0]:.6f}, {coord[1]:.6f}")
    
    st.markdown("---")
    st.subheader("💡 Tips")
    st.markdown("""
    1. Use **sample.kml** to test
    2. Adjust **scale** if needed
    3. Open in **AutoCAD** or **LibreCAD**
    4. File should be **> 1KB**
    """)
    
    # Create sample KML
    sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Test Data</name>
  
  <Placemark>
    <name>Location A</name>
    <Point>
      <coordinates>107.609, -6.914, 0</coordinates>
    </Point>
  </Placemark>
  
  <Placemark>
    <name>Path AB</name>
    <LineString>
      <coordinates>
        107.609, -6.914, 0
        107.610, -6.915, 0
        107.611, -6.916, 0
      </coordinates>
    </LineString>
  </Placemark>
  
  <Placemark>
    <name>Area 1</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            107.600, -6.900, 0
            107.605, -6.900, 0
            107.605, -6.905, 0
            107.600, -6.905, 0
            107.600, -6.900, 0
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
        "sample.kml",
        "text/xml",
        use_container_width=True
    )

# Debug section
with st.expander("🔧 Debug Info", expanded=False):
    if st.session_state.converter:
        converter = st.session_state.converter
        st.write("**Statistics:**")
        st.json(converter.stats)
        
        if converter.geometries:
            st.write(f"**Geometries ({len(converter.geometries)}):**")
            for i, geom in enumerate(converter.geometries[:5]):
                st.write(f"{i+1}. {geom['type']} - {geom['name']}")
                if geom['coords']:
                    st.write(f"   Coordinates: {len(geom['coords'])} points")

# Footer
st.markdown("---")
st.caption("KML to DXF Converter • Simple and reliable conversion")
