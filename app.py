import xml.etree.ElementTree as ET
import argparse
import os
import sys

class KMLtoDXFConverter:
    def __init__(self):
        self.namespace = {'kml': 'http://www.opengis.net/kml/2.2'}
        self.dxf_entities = []
        self.layers = {}
        self.color_map = {
            'red': 1, 'green': 3, 'blue': 5, 'yellow': 2,
            'purple': 6, 'cyan': 4, 'white': 7, 'black': 0
        }
    
    def parse_color(self, color_str):
        """Parse KML color format (aabbggrr) to DXF color index"""
        if not color_str:
            return 7  # Default white
        
        # KML color format: aabbggrr (alpha, blue, green, red)
        if color_str.startswith('#'):
            color_str = color_str[1:]
        
        if len(color_str) == 8:
            rr = color_str[6:8]  # Red component
            # Convert to simple color index based on brightness
            r_val = int(rr, 16)
            if r_val > 200:
                return 1  # Red
            elif r_val > 100:
                return 2  # Yellow
            else:
                return 7  # White
        return 7
    
    def parse_coordinates(self, coord_text):
        """Parse coordinates string to list of (x, y, z) tuples"""
        coords = []
        if not coord_text:
            return coords
        
        lines = coord_text.strip().split()
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2:
                x = float(parts[0])
                y = float(parts[1])
                z = float(parts[2]) if len(parts) >= 3 else 0.0
                coords.append((x, y, z))
        return coords
    
    def extract_style(self, placemark):
        """Extract style information from placemark"""
        style = {
            'color': 7,  # Default white
            'layer': '0',
            'linetype': 'CONTINUOUS'
        }
        
        # Try to get styleUrl
        style_url = placemark.find('.//kml:styleUrl', self.namespace)
        if style_url is not None and style_url.text:
            style_id = style_url.text.replace('#', '')
            
            # Find the style definition
            style_def = placemark.getroot().find(f".//kml:Style[@id='{style_id}']", self.namespace)
            if style_def is None:
                # Try in Document
                doc = placemark.find('..')
                if doc is not None:
                    style_def = doc.find(f".//kml:Style[@id='{style_id}']", self.namespace)
            
            if style_def is not None:
                # Get line style
                line_style = style_def.find('.//kml:LineStyle', self.namespace)
                if line_style is not None:
                    color_elem = line_style.find('.//kml:color', self.namespace)
                    if color_elem is not None:
                        style['color'] = self.parse_color(color_elem.text)
        
        # Get name for layer
        name_elem = placemark.find('.//kml:name', self.namespace)
        if name_elem is not None and name_elem.text:
            style['layer'] = name_elem.text[:31]  # DXF layer names max 31 chars
        
        return style
    
    def process_point(self, placemark, coordinates, style):
        """Process Point geometry"""
        if coordinates:
            x, y, z = coordinates[0]
            self.dxf_entities.append({
                'type': 'POINT',
                'x': x, 'y': y, 'z': z,
                'layer': style['layer'],
                'color': style['color']
            })
    
    def process_linestring(self, placemark, coordinates, style):
        """Process LineString geometry"""
        if len(coordinates) < 2:
            return
        
        # Create LWPOLYLINE for 2D or 3DPOLYLINE for 3D
        has_z = any(coord[2] != 0 for coord in coordinates)
        
        if has_z:
            self.dxf_entities.append({
                'type': '3DPOLYLINE',
                'vertices': coordinates,
                'layer': style['layer'],
                'color': style['color'],
                'closed': False
            })
        else:
            # Convert to 2D vertices
            vertices_2d = [(x, y) for x, y, z in coordinates]
            self.dxf_entities.append({
                'type': 'LWPOLYLINE',
                'vertices': vertices_2d,
                'layer': style['layer'],
                'color': style['color'],
                'closed': False
            })
    
    def process_polygon(self, placemark, coordinates, style):
        """Process Polygon geometry"""
        if len(coordinates) < 3:
            return
        
        has_z = any(coord[2] != 0 for coord in coordinates)
        
        if has_z:
            self.dxf_entities.append({
                'type': '3DPOLYLINE',
                'vertices': coordinates,
                'layer': style['layer'],
                'color': style['color'],
                'closed': True
            })
        else:
            vertices_2d = [(x, y) for x, y, z in coordinates]
            self.dxf_entities.append({
                'type': 'LWPOLYLINE',
                'vertices': vertices_2d,
                'layer': style['layer'],
                'color': style['color'],
                'closed': True
            })
    
    def process_geometry(self, placemark, geometry):
        """Process geometry element"""
        style = self.extract_style(placemark)
        
        # Handle different geometry types
        geom_type = geometry.tag.split('}')[-1]
        
        if geom_type == 'Point':
            coord_elem = geometry.find('.//kml:coordinates', self.namespace)
            if coord_elem is not None:
                coords = self.parse_coordinates(coord_elem.text)
                self.process_point(placemark, coords, style)
        
        elif geom_type == 'LineString':
            coord_elem = geometry.find('.//kml:coordinates', self.namespace)
            if coord_elem is not None:
                coords = self.parse_coordinates(coord_elem.text)
                self.process_linestring(placemark, coords, style)
        
        elif geom_type == 'Polygon':
            outer_boundary = geometry.find('.//kml:outerBoundaryIs', self.namespace)
            if outer_boundary is not None:
                linear_ring = outer_boundary.find('.//kml:LinearRing', self.namespace)
                if linear_ring is not None:
                    coord_elem = linear_ring.find('.//kml:coordinates', self.namespace)
                    if coord_elem is not None:
                        coords = self.parse_coordinates(coord_elem.text)
                        self.process_polygon(placemark, coords, style)
    
    def parse_kml(self, kml_file):
        """Parse KML file and extract geometries"""
        try:
            tree = ET.parse(kml_file)
            root = tree.getroot()
            
            # Find all placemarks
            placemarks = root.findall('.//kml:Placemark', self.namespace)
            
            if not placemarks:
                # Try alternative namespace
                self.namespace = {'kml': 'http://earth.google.com/kml/2.0'}
                placemarks = root.findall('.//kml:Placemark', self.namespace)
            
            print(f"Found {len(placemarks)} placemarks")
            
            for placemark in placemarks:
                # Get geometry
                geometry = placemark.find('.//kml:Point', self.namespace)
                if geometry is not None:
                    self.process_geometry(placemark, geometry)
                    continue
                
                geometry = placemark.find('.//kml:LineString', self.namespace)
                if geometry is not None:
                    self.process_geometry(placemark, geometry)
                    continue
                
                geometry = placemark.find('.//kml:Polygon', self.namespace)
                if geometry is not None:
                    self.process_geometry(placemark, geometry)
                    continue
                
                # Try MultiGeometry
                multi_geom = placemark.find('.//kml:MultiGeometry', self.namespace)
                if multi_geom is not None:
                    geometries = multi_geom.findall('*')
                    for geom in geometries:
                        self.process_geometry(placemark, geom)
            
            print(f"Processed {len(self.dxf_entities)} DXF entities")
            
        except ET.ParseError as e:
            print(f"Error parsing KML file: {e}")
            return False
        except Exception as e:
            print(f"Error processing KML: {e}")
            return False
        
        return True
    
    def write_dxf(self, dxf_file):
        """Write DXF file (simplified ASCII DXF format)"""
        try:
            with open(dxf_file, 'w', encoding='utf-8') as f:
                # DXF Header
                f.write("0\nSECTION\n")
                f.write("2\nHEADER\n")
                f.write("9\n$ACADVER\n1\nAC1009\n")  # R12 format for compatibility
                f.write("9\n$INSBASE\n10\n0.0\n20\n0.0\n30\n0.0\n")
                f.write("0\nENDSEC\n")
                
                # Tables Section
                f.write("0\nSECTION\n")
                f.write("2\nTABLES\n")
                
                # Layer Table
                f.write("0\nTABLE\n")
                f.write("2\nLAYER\n")
                f.write("70\n1\n")  # Number of layers
                
                # Default layer
                f.write("0\nLAYER\n")
                f.write("2\n0\n")  # Layer name
                f.write("70\n0\n")  # Flags
                f.write("62\n7\n")  # Color (white)
                f.write("6\nCONTINUOUS\n")  # Linetype
                
                f.write("0\nENDTAB\n")
                f.write("0\nENDSEC\n")
                
                # Entities Section
                f.write("0\nSECTION\n")
                f.write("2\nENTITIES\n")
                
                for entity in self.dxf_entities:
                    if entity['type'] == 'POINT':
                        f.write("0\nPOINT\n")
                        f.write(f"8\n{entity['layer']}\n")  # Layer
                        f.write(f"62\n{entity['color']}\n")  # Color
                        f.write(f"10\n{entity['x']}\n")  # X
                        f.write(f"20\n{entity['y']}\n")  # Y
                        f.write(f"30\n{entity['z']}\n")  # Z
                    
                    elif entity['type'] == 'LWPOLYLINE':
                        f.write("0\nLWPOLYLINE\n")
                        f.write(f"8\n{entity['layer']}\n")
                        f.write(f"62\n{entity['color']}\n")
                        f.write(f"90\n{len(entity['vertices'])}\n")  # Number of vertices
                        f.write(f"70\n{1 if entity['closed'] else 0}\n")  # Closed flag
                        
                        for x, y in entity['vertices']:
                            f.write(f"10\n{x}\n")
                            f.write(f"20\n{y}\n")
                    
                    elif entity['type'] == '3DPOLYLINE':
                        f.write("0\nPOLYLINE\n")
                        f.write(f"8\n{entity['layer']}\n")
                        f.write(f"62\n{entity['color']}\n")
                        f.write("66\n1\n")  # Vertices follow
                        f.write(f"70\n{8 if entity['closed'] else 0}\n")  # 3D polyline flag + closed
                        
                        for x, y, z in entity['vertices']:
                            f.write("0\nVERTEX\n")
                            f.write(f"8\n{entity['layer']}\n")
                            f.write(f"10\n{x}\n")
                            f.write(f"20\n{y}\n")
                            f.write(f"30\n{z}\n")
                        
                        f.write("0\nSEQEND\n")
                
                f.write("0\nENDSEC\n")
                f.write("0\nEOF\n")
            
            print(f"Successfully wrote DXF file: {dxf_file}")
            return True
            
        except Exception as e:
            print(f"Error writing DXF file: {e}")
            return False
    
    def convert(self, kml_file, dxf_file):
        """Main conversion method"""
        print(f"Converting {kml_file} to {dxf_file}")
        
        if not os.path.exists(kml_file):
            print(f"Error: KML file not found: {kml_file}")
            return False
        
        # Parse KML
        if not self.parse_kml(kml_file):
            return False
        
        # Write DXF
        if not self.write_dxf(dxf_file):
            return False
        
        return True

def main():
    parser = argparse.ArgumentParser(description='Convert KML to DXF format')
    parser.add_argument('input', help='Input KML file')
    parser.add_argument('output', help='Output DXF file')
    parser.add_argument('--version', action='version', version='KML to DFX Converter 1.0')
    
    args = parser.parse_args()
    
    # Check file extensions
    if not args.input.lower().endswith('.kml'):
        print("Warning: Input file should have .kml extension")
    
    if not args.output.lower().endswith('.dxf'):
        args.output = args.output + '.dxf'
    
    # Perform conversion
    converter = KMLtoDXFConverter()
    success = converter.convert(args.input, args.output)
    
    if success:
        print("Conversion completed successfully!")
        return 0
    else:
        print("Conversion failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
