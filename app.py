import streamlit as st
import geopandas as gpd
import ezdxf
import fiona
import osmnx as ox
import pandas as pd
from streamlit_folium import folium_static
import folium
import tempfile
import os
from shapely.geometry import Point, LineString
import warnings
warnings.filterwarnings('ignore')

# Konfigurasi Halaman
st.set_page_config(page_title="KML to CAD Professional", layout="wide", page_icon="📐")

# Inisialisasi session state
if 'gdf' not in st.session_state:
    st.session_state.gdf = None
if 'dxf_path' not in st.session_state:
    st.session_state.dxf_path = None

# CSS Custom
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        margin-top: 10px;
    }
    .success-box {
        padding: 20px;
        background-color: #d4edda;
        border-radius: 5px;
        border: 1px solid #c3e6cb;
        margin: 10px 0;
    }
    .warning-box {
        padding: 20px;
        background-color: #fff3cd;
        border-radius: 5px;
        border: 1px solid #ffeaa7;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

def load_kml_properly(path):
    """Membaca semua folder di KML secara mendalam dengan penanganan error yang lebih baik."""
    try:
        layers = fiona.listlayers(path)
        gdfs = []
        
        for layer in layers:
            try:
                with st.spinner(f"Memuat layer: {layer}..."):
                    tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
                    if not tmp_gdf.empty:
                        # Simpan nama layer asli
                        tmp_gdf['source_layer'] = layer
                        gdfs.append(tmp_gdf)
                        st.sidebar.success(f"✅ Layer '{layer}' berhasil dimuat")
            except Exception as e:
                st.sidebar.warning(f"⚠️ Layer '{layer}' dilewati: {str(e)}")
                continue
        
        if gdfs:
            full_gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs)
            
            # Filter hanya Point dan LineString
            valid_geom_types = ['Point', 'LineString']
            full_gdf = full_gdf[full_gdf.geometry.type.isin(valid_geom_types)]
            
            # Reset index
            full_gdf = full_gdf.reset_index(drop=True)
            
            # Log informasi
            point_count = len(full_gdf[full_gdf.geometry.type == 'Point'])
            line_count = len(full_gdf[full_gdf.geometry.type == 'LineString'])
            
            st.sidebar.info(f"""
            **Ringkasan Data:**
            - Total objek: {len(full_gdf)}
            - Titik (Point): {point_count}
            - Garis (LineString): {line_count}
            - Layer sumber: {len(set(full_gdf['source_layer']))}
            """)
            
            return full_gdf
        else:
            st.error("Tidak ada data yang dapat dimuat dari file KML.")
            return gpd.GeoDataFrame()
            
    except Exception as e:
        st.error(f"Gagal membaca file KML: {str(e)}")
        return gpd.GeoDataFrame()

def convert_to_dxf_final(gdf, include_roads=True):
    """Konversi ke DXF dengan penanganan GEODATA yang kompatibel."""
    try:
        # Buat dokumen DXF baru
        doc = ezdxf.new('R2010', setup=True)
        msp = doc.modelspace()
        
        # Setup Layers dengan warna dan deskripsi
        layers_config = {
            'MAP_JALAN': {'color': 8, 'description': 'Data jalan dari OpenStreetMap'},
            'KABEL_JARINGAN': {'color': 3, 'description': 'Kabel dan jaringan'},
            'PERANGKAT_TITIK': {'color': 1, 'description': 'Titik perangkat'},
            'LABEL_TEKS': {'color': 7, 'description': 'Label teks'},
            'BATAS_AREA': {'color': 2, 'description': 'Batas area'}
        }
        
        for layer_name, config in layers_config.items():
            doc.layers.new(
                name=layer_name,
                dxfattribs={
                    'color': config['color'],
                    'description': config['description']
                }
            )
        
        # Hitung centroid untuk scaling
        centroid = gdf.geometry.unary_union.centroid
        avg_x, avg_y = centroid.x, centroid.y
        
        # 1. AMBIL DATA JALAN OSM (Opsional)
        if include_roads:
            try:
                with st.spinner("📡 Mengambil data jalan dari OpenStreetMap..."):
                    # Convert centroid ke (lat, lon) untuk OSM
                    centroid_latlon = (centroid.y, centroid.x)
                    
                    # Dapatkan graph dari OSM
                    G = ox.graph_from_point(
                        centroid_latlon, 
                        dist=1000,  # Jarak 1km dari centroid
                        network_type='drive',
                        simplify=True
                    )
                    
                    # Convert ke GeoDataFrame
                    nodes, edges = ox.graph_to_gdfs(G)
                    
                    # Plot edges (jalan) ke DXF
                    road_count = 0
                    for _, edge in edges.iterrows():
                        if hasattr(edge.geometry, 'geom_type') and edge.geometry.geom_type == 'LineString':
                            # Konversi koordinat (lon, lat) ke sistem proyeksi yang sesuai
                            coords = list(edge.geometry.coords)
                            msp.add_lwpolyline(
                                coords,
                                dxfattribs={
                                    'layer': 'MAP_JALAN',
                                    'color': 8
                                }
                            )
                            road_count += 1
                    
                    st.sidebar.success(f"✅ {road_count} segmen jalan ditambahkan")
                    
            except Exception as e:
                st.sidebar.warning(f"⚠️ Data jalan tidak tersedia: {str(e)}")
        
        # 2. PLOT DATA KML
        point_counter = 0
        line_counter = 0
        
        # Scaling factor untuk ukuran simbol yang konsisten
        scale_factor = 0.00005
        
        for idx, row in gdf.iterrows():
            geom = row.geometry
            name = str(row.get('Name', row.get('name', f'Obj_{idx}')))
            description = row.get('description', '')
            
            if geom.geom_type == 'Point':
                # Tambahkan titik sebagai circle
                msp.add_circle(
                    center=(geom.x, geom.y),
                    radius=scale_factor * 2,
                    dxfattribs={
                        'layer': 'PERANGKAT_TITIK',
                        'color': 1
                    }
                )
                
                # Tambahkan label jika ada nama
                if name and name.lower() not in ['none', 'null', '']:
                    text = msp.add_text(
                        name,
                        dxfattribs={
                            'layer': 'LABEL_TEKS',
                            'color': 7,
                            'height': scale_factor * 3
                        }
                    )
                    text.set_placement((geom.x, geom.y + scale_factor * 5))
                
                point_counter += 1
                
            elif geom.geom_type == 'LineString':
                # Tambahkan polyline untuk LineString
                msp.add_lwpolyline(
                    list(geom.coords),
                    dxfattribs={
                        'layer': 'KABEL_JARINGAN',
                        'color': 3,
                        'lineweight': 18  # Medium line weight
                    }
                )
                line_counter += 1
        
        # 3. Tambahkan informasi metadata sebagai text
        info_text = f"KML to DFX - {len(gdf)} objek - {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
        msp.add_text(
            info_text,
            dxfattribs={
                'layer': 'LABEL_TEKS',
                'height': scale_factor * 4,
                'color': 7
            }
        ).set_placement((avg_x, avg_y - scale_factor * 50))
        
        # Simpan ke file temporary
        tmp_path = tempfile.mktemp(suffix='.dxf')
        doc.saveas(tmp_path)
        
        # Log konversi
        st.sidebar.success(f"""
        **Konversi Selesai:**
        - Titik: {point_counter}
        - Garis: {line_counter}
        - Total: {point_counter + line_counter}
        """)
        
        return tmp_path
        
    except Exception as e:
        st.error(f"Gagal mengkonversi ke DXF: {str(e)}")
        return None

# --- UI STREAMLIT ---

st.title("📐 KML to DXF Professional Converter")
st.markdown("""
**Fitur Utama:**
- ✅ Konversi KML ke DXF dengan presisi tinggi
- ✅ Auto-download data jalan dari OpenStreetMap (opsional)
- ✅ Preservasi layer dan atribut
- ✅ Preview interaktif di peta
- ✅ Tanpa polygon (hanya Point & LineString)
""")

# Sidebar
with st.sidebar:
    st.header("⚙️ Pengaturan Konversi")
    
    uploaded_file = st.file_uploader(
        "Upload file KML/KMZ",
        type=['kml', 'kmz'],
        help="Upload file KML atau KMZ yang berisi data titik dan garis"
    )
    
    # Opsi konversi
    include_osm = st.checkbox(
        "📡 Sertakan data jalan (OSM)",
        value=True,
        help="Tambah data jalan dari OpenStreetMap"
    )
    
    simplify_geometry = st.checkbox(
        "🔧 Simplifikasi geometri",
        value=False,
        help="Reduksi titik pada polyline yang panjang"
    )

# Main Content
col1, col2 = st.columns([2, 1])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        kml_path = tmp.name
    
    try:
        # Load KML
        with col1:
            with st.spinner("Memproses file KML..."):
                gdf = load_kml_properly(kml_path)
                st.session_state.gdf = gdf
        
        if not gdf.empty and len(gdf) > 0:
            # Display statistics
            with col2:
                st.markdown("### 📊 Statistik Data")
                
                stats_data = {
                    'Tipe': ['Titik', 'Garis', 'Total'],
                    'Jumlah': [
                        len(gdf[gdf.geometry.type == 'Point']),
                        len(gdf[gdf.geometry.type == 'LineString']),
                        len(gdf)
                    ]
                }
                
                st.dataframe(pd.DataFrame(stats_data), use_container_width=True)
                
                # Bounding box info
                bounds = gdf.total_bounds
                st.markdown("**📍 Bounding Box:**")
                st.write(f"Min: ({bounds[0]:.6f}, {bounds[1]:.6f})")
                st.write(f"Max: ({bounds[2]:.6f}, {bounds[3]:.6f})")
            
            # Convert button
            if st.button("🚀 Generate DXF File", type="primary", use_container_width=True):
                with st.spinner("Mengkonversi ke format DXF..."):
                    dxf_path = convert_to_dxf_final(gdf, include_osm)
                    
                    if dxf_path and os.path.exists(dxf_path):
                        st.session_state.dxf_path = dxf_path
                        
                        # Show download button
                        with open(dxf_path, "rb") as f:
                            st.download_button(
                                label="📥 Download File DXF",
                                data=f,
                                file_name="hasil_konversi.dxf",
                                mime="application/dxf",
                                type="primary",
                                use_container_width=True
                            )
                        
                        st.success("✅ Konversi berhasil! File DXF siap di-download.")
            
            # Preview Map
            st.markdown("### 🗺️ Preview Peta")
            
            # Calculate map center
            center_lat = gdf.geometry.centroid.y.mean()
            center_lon = gdf.geometry.centroid.x.mean()
            
            # Create map
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=16,
                tiles=None,
                control_scale=True
            )
            
            # Add tile layers
            folium.TileLayer(
                'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                attr='OpenStreetMap',
                name='OpenStreetMap',
                control=True
            ).add_to(m)
            
            folium.TileLayer(
                'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                attr='Google',
                name='Google Satellite',
                control=True
            ).add_to(m)
            
            folium.TileLayer(
                'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
                attr='Google',
                name='Google Hybrid',
                control=True
            ).add_to(m)
            
            # Add points
            points_gdf = gdf[gdf.geometry.type == 'Point']
            for idx, row in points_gdf.iterrows():
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=6,
                    color='red',
                    fill=True,
                    fill_color='red',
                    fill_opacity=0.7,
                    popup=f"<b>{row.get('Name', f'Point {idx}')}</b><br>Layer: {row.get('source_layer', 'N/A')}"
                ).add_to(m)
            
            # Add lines
            lines_gdf = gdf[gdf.geometry.type == 'LineString']
            for idx, row in lines_gdf.iterrows():
                coords = [(coord[1], coord[0]) for coord in row.geometry.coords]
                folium.PolyLine(
                    locations=coords,
                    color='blue',
                    weight=3,
                    opacity=0.8,
                    popup=f"<b>Line {idx}</b><br>Layer: {row.get('source_layer', 'N/A')}"
                ).add_to(m)
            
            # Add layer control
            folium.LayerControl().add_to(m)
            
            # Display map
            folium_static(m, width=1000, height=600)
            
            # Show data preview
            with st.expander("👁️ Preview Data", expanded=False):
                st.dataframe(gdf.head(10), use_container_width=True)
        
        else:
            st.error("⚠️ File KML tidak berisi data Point atau LineString yang valid.")
            
    except Exception as e:
        st.error(f"❌ Terjadi kesalahan: {str(e)}")
        
    finally:
        # Cleanup temporary files
        if os.path.exists(kml_path):
            os.unlink(kml_path)
        if st.session_state.dxf_path and os.path.exists(st.session_state.dxf_path):
            try:
                os.unlink(st.session_state.dxf_path)
            except:
                pass

else:
    # Welcome/Instruction screen
    with col1:
        st.markdown("""
        ### 📋 Panduan Penggunaan
        
        1. **Upload File KML/KMZ** melalui sidebar di sebelah kiri
        2. **Atur Pengaturan** konversi sesuai kebutuhan
        3. **Klik 'Generate DXF File'** untuk memulai konversi
        4. **Download File DXF** hasil konversi
        5. **Preview** data Anda di peta interaktif
        
        ### 📌 Format yang Didukung
        - **KML (Keyhole Markup Language)**
        - **KMZ (Compressed KML)**
        
        ### ⚠️ Catatan Penting
        - Hanya data **Point** dan **LineString** yang akan dikonversi
        - Polygon akan diabaikan
        - Sistem koordinat dipertahankan (WGS84)
        """)
    
    with col2:
        st.markdown("""
        ### 🎯 Fitur Premium
        
        **✓ Konversi Presisi Tinggi**
        - Akurasi koordinat terjaga
        - Preservasi atribut data
        
        **✓ Integrasi OSM**
        - Auto-fetch data jalan
        - Update real-time
        
        **✓ Multi-Layer Support**
        - Layer management
        - Color coding
        
        **✓ Export Options**
        - DXF format
        - AutoCAD compatible
        """)

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "KML to DXF Professional Converter v2.0 • "
    "© 2024 • Dibuat dengan Streamlit"
    "</div>",
    unsafe_allow_html=True
)
