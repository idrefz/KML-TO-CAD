import argparse
import os
import sys
import xml.etree.ElementTree as ET
import ezdxf
from ezdxf import colors

class EnhancedKMLtoDXFConverter:
    def __init__(self):
        self.namespace = {'kml': 'http://www.opengis.net/kml/2.2'}
        self.entities = []
        
    def parse_coordinates(self, coord_text):
        """Parse coordinates string"""
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
    
    def kml_color_to_dxf(self, kml_color):
        """Convert KML color to DXF color"""
        if not kml_color or not kml_color.startswith('#'):
            return colors.WHITE
        
        # KML: #aabbggrr to RGB
        color_hex = kml_color[1:]
        if len(color_hex) == 8:
            rr = color_hex[6:8]
            gg = color_hex[4:6]
            bb = color_hex[2:4]
            return (int(rr, 16), int(gg, 16), int(bb, 16))
        
        return colors.WHITE
    
    def extract_placemark_info(self, placemark):
        """Extract information from placemark"""
        info = {
            'name': 'Unnamed',
            'description': '',
            'style': {},
            'geometry_type': None,
            'coordinates': []
        }
        
        # Name
        name_elem = placemark.find('.//kml:name', self.namespace)
        if name_elem is not None and name_elem.text:
            info['name'] = name_elem.text
        
        # Description
        desc_elem = placemark.find('.//kml:description', self.namespace)
        if desc_elem is not None and desc_elem.text:
            info['description'] = desc_elem.text
        
        # Style
        style_url = placemark.find('.//kml:styleUrl', self.namespace)
        if style_url is not None and style_url.text:
            style_id = style_url.text.replace('#', '')
            
            # Find style definition
            root = placemark.getroot()
            style_def = root.find(f".//kml:Style[@id='{style_id}']", self.namespace)
            
            if style_def is None:
                # Check parent elements
                parent = placemark.find('..')
                if parent is not None:
                    style_def = parent.find(f".//kml:Style[@id='{style_id}']", self.namespace)
            
            if style_def is not None:
                # Line style
                line_style = style_def.find('.//kml:LineStyle', self.namespace)
                if line_style is not None:
                    color_elem = line_style.find('.//kml:color', self.namespace)
                    if color_elem is not None:
                        info['style']['color'] = self.kml_color_to_dxf(color_elem.text)
                    
                    width_elem = line_style.find('.//kml:width', self.namespace)
                    if width_elem is not None:
                        info['style']['width'] = float(width_elem.text)
                
                # Polygon style
                poly_style = style_def.find('.//kml:PolyStyle', self.namespace)
                if poly_style is not None:
                    fill_elem = poly_style.find('.//kml:fill', self.namespace)
                    if fill_elem is not None:
                        info['style']['fill'] = int(fill_elem.text)
        
        return info
    
    def process_kml(self, kml_file):
        """Process KML file"""
        try:
            tree = ET.parse(kml_file)
            root = tree.getroot()
            
            # Register namespace
            if '}' in root.tag:
                ns = root.tag.split('}')[0].strip('{')
                self.namespace['kml'] = ns
            
            # Find all placemarks
            placemarks = root.findall('.//kml:Placemark', self.namespace)
            
            if not placemarks:
                print("No placemarks found. Trying alternative namespace...")
                # Try common namespaces
                for ns in ['http://earth.google.com/kml/2.0', 
                          'http://earth.google.com/kml/2.1',
                          'http://www.opengis.net/kml/2.1']:
                    self.namespace['kml'] = ns
                    placemarks = root.findall('.//kml:Placemark', self.namespace)
                    if placemarks:
                        break
            
            print(f"Found {len(placemarks)} placemarks")
            
            for pm in placemarks:
                info = self.extract_placemark_info(pm)
                
                # Check geometry types
                geometry = None
                geom_type = None
                
                # Point
                geom = pm.find('.//kml:Point', self.namespace)
                if geom is not None:
                    geometry = geom
                    geom_type = 'POINT'
                
                # LineString
                if geom_type is None:
                    geom = pm.find('.//kml:LineString', self.namespace)
                    if geom is not None:
                        geometry = geom
                        geom_type = 'LINE'
                
                # Polygon
                if geom_type is None:
                    geom = pm.find('.//kml:Polygon', self.namespace)
                    if geom is not None:
                        geometry = geom
                        geom_type = 'POLYGON'
                
                # MultiGeometry
                if geom_type is None:
                    geom = pm.find('.//kml:MultiGeometry', self.namespace)
                    if geom is not None:
                        geometry = geom
                        geom_type = 'MULTI'
                
                if geometry is not None:
                    info['geometry_type'] = geom_type
                    
                    # Get coordinates
                    if geom_type == 'POLYGON':
                        outer = geometry.find('.//kml:outerBoundaryIs', self.namespace)
                        if outer is not None:
                            ring = outer.find('.//kml:LinearRing', self.namespace)
                            if ring is not None:
                                coords_elem = ring.find('.//kml:coordinates', self.namespace)
                                if coords_elem is not None:
                                    info['coordinates'] = self.parse_coordinates(coords_elem.text)
                    else:
                        coords_elem = geometry.find('.//kml:coordinates', self.namespace)
                        if coords_elem is not None:
                            info['coordinates'] = self.parse_coordinates(coords_elem.text)
                    
                    # For MultiGeometry, process each sub-geometry
                    if geom_type == 'MULTI':
                        sub_geometries = []
                        for subgeom in geometry:
                            sub_type = subgeom.tag.split('}')[-1]
                            sub_coords = []
                            
                            if sub_type == 'Polygon':
                                outer = subgeom.find('.//kml:outerBoundaryIs', self.namespace)
                                if outer is not None:
                                    ring = outer.find('.//kml:LinearRing', self.namespace)
                                    if ring is not None:
                                        coords_elem = ring.find('.//kml:coordinates', self.namespace)
                                        if coords_elem is not None:
                                            sub_coords = self.parse_coordinates(coords_elem.text)
                            else:
                                coords_elem = subgeom.find('.//kml:coordinates', self.namespace)
                                if coords_elem is not None:
                                    sub_coords = self.parse_coordinates(coords_elem.text)
                            
                            if sub_coords:
                                sub_geometries.append({
                                    'type': sub_type,
                                    'coordinates': sub_coords
                                })
                        
                        info['sub_geometries'] = sub_geometries
                    
                    self.entities.append(info)
            
            return True
            
        except Exception as e:
            print(f"Error processing KML: {e}")
            return False
    
    def convert(self, kml_file, dxf_file):
        """Convert KML to DXF using ezdxf"""
        print(f"Converting {kml_file} to {dxf_file}")
        
        if not os.path.exists(kml_file):
            print(f"Error: File not found: {kml_file}")
            return False
        
        # Process KML
        if not self.process_kml(kml_file):
            return False
        
        # Create DXF document
        doc = ezdxf.new('R2010')  # Use AutoCAD 2010 format
        msp = doc.modelspace()
        
        # Create layers based on entity names
        layers_created = set()
        
        for entity in self.entities:
            layer_name = entity['name'][:31]  # DXF limit
            if layer_name not in layers_created:
                doc.layers.new(name=layer_name)
                layers_created.add(layer_name)
            
            color = entity['style'].get('color', colors.WHITE)
            
            if entity['geometry_type'] == 'POINT' and entity['coordinates']:
                for x, y, z in entity['coordinates']:
                    msp.add_point((x, y, z), 
                                 dxfattribs={'layer': layer_name, 'color': color})
            
            elif entity['geometry_type'] == 'LINE' and len(entity['coordinates']) >= 2:
                if len(entity['coordinates']) == 2:
                    # Simple line
                    start = entity['coordinates'][0]
                    end = entity['coordinates'][1]
                    msp.add_line(start, end, 
                                dxfattribs={'layer': layer_name, 'color': color})
                else:
                    # Polyline
                    msp.add_polyline3d(entity['coordinates'], 
                                      dxfattribs={'layer': layer_name, 'color': color})
            
            elif entity['geometry_type'] == 'POLYGON' and len(entity['coordinates']) >= 3:
                # Close the polygon if not closed
                coords = entity['coordinates']
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                
                msp.add_polyline3d(coords, 
                                  dxfattribs={'layer': layer_name, 'color': color})
            
            elif entity['geometry_type'] == 'MULTI' and 'sub_geometries' in entity:
                for sub in entity['sub_geometries']:
                    if sub['type'] == 'Point':
                        for x, y, z in sub['coordinates']:
                            msp.add_point((x, y, z), 
                                         dxfattribs={'layer': layer_name, 'color': color})
                    elif sub['type'] in ['LineString', 'Polygon'] and sub['coordinates']:
                        coords = sub['coordinates']
                        if sub['type'] == 'Polygon' and len(coords) >= 3:
                            if coords[0] != coords[-1]:
                                coords.append(coords[0])
                        
                        if len(coords) == 2:
                            msp.add_line(coords[0], coords[1], 
                                        dxfattribs={'layer': layer_name, 'color': color})
                        else:
                            msp.add_polyline3d(coords, 
                                              dxfattribs={'layer': layer_name, 'color': color})
        
        # Save DXF file
        try:
            doc.saveas(dxf_file)
            print(f"Successfully created DXF file: {dxf_file}")
            print(f"Total entities converted: {len(self.entities)}")
            return True
        except Exception as e:
            print(f"Error saving DXF file: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(
        description='Convert KML (Keyhole Markup Language) to DXF (Drawing Exchange Format)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.kml output.dxf
  %(prog)s "C:\\My Files\\map.kml" "C:\\Output\\drawing.dxf"
  %(prog)s data.kml --output converted.dxf
        """
    )
    
    parser.add_argument('input', help='Input KML file path')
    parser.add_argument('output', nargs='?', help='Output DXF file path (optional)')
    parser.add_argument('-o', '--output', dest='output_file', 
                       help='Specify output DXF file path')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show detailed conversion information')
    parser.add_argument('--version', action='version', 
                       version='KML to DXF Converter 2.0')
    
    args = parser.parse_args()
    
    # Determine output file
    if args.output_file:
        output_path = args.output_file
    elif args.output:
        output_path = args.output
    else:
        # Auto-generate output filename
        base_name = os.path.splitext(args.input)[0]
        output_path = base_name + '.dxf'
    
    # Check input file
    if not os.path.exists(args.input):
        print(f"Error: Input file does not exist: {args.input}")
        return 1
    
    if not args.input.lower().endswith('.kml'):
        print("Warning: Input file should have .kml extension")
    
    # Perform conversion
    converter = EnhancedKMLtoDXFConverter()
    
    if args.verbose:
        print("Starting KML to DXF conversion...")
        print(f"Input:  {args.input}")
        print(f"Output: {output_path}")
    
    success = converter.convert(args.input, output_path)
    
    if success:
        if args.verbose:
            print("Conversion completed successfully!")
        return 0
    else:
        print("Conversion failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
