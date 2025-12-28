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
        padding: 10px;
        background-color: #d4edda;
        border-radius: 5px;
        border: 1px solid #c3e6cb;
        margin: 5px 0;
    }
    .warning-box {
        padding: 10px;
        background-color: #fff3cd;
        border-radius: 5px;
        border: 1px solid #ffeaa7;
        margin: 5px 0;
    }
    .info-box {
        padding: 10px;
        background-color: #d1ecf1;
        border-radius: 5px;
        border: 1px solid #bee5eb;
        margin: 5px 0;
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
                tmp_gdf = gpd.read_file(path, layer=layer, driver='KML')
                if not tmp_gdf.empty:
                    # Simpan nama layer asli
                    tmp_gdf['source_layer'] = layer
                    gdfs.append(tmp_gdf)
                    st.sidebar.info(f"✅ Layer '{layer}': {len(tmp_gdf)} objek")
            except Exception as e:
                st.sidebar.warning(f"⚠️ Layer '{layer}' dilewati: {str(e)[:50]}...")
                continue
        
        if gdfs:
            full_gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs)
            
            # Filter hanya Point dan LineString
            valid_geom_types = ['Point', 'LineString']
            full_gdf = full_gdf[full_gdf.geometry.type.isin(valid_geom_types)]
            
            # Reset index
            full_gdf = full_gdf.reset_index(drop=True)
            
            return full_gdf
        else:
            return gpd.GeoDataFrame()
            
    except Exception as e:
        st.error(f"Gagal membaca file KML: {str(e)}")
        return gpd.GeoDataFrame()

def convert_to_dxf_final(gdf, include_roads=True):
    """Konversi ke DXF dengan penanganan yang lebih sederhana."""
    try:
        # Buat dokumen DXF baru
        doc = ezdxf.new('R2010', setup=True)
        msp = doc.modelspace()
        
        # Setup Layers dengan warna yang sesuai
        # Layer: MAP_JALAN (warna 8 - abu-abu)
        doc.layers.new(name='MAP_JALAN', dxfattribs={'color': 8})
        
        # Layer: KABEL_JARINGAN (warna 3 - hijau)
        doc.layers.new(name='KABEL_JARINGAN', dxfattribs={'color': 3})
        
        # Layer: PERANGKAT_TITIK (warna 1 - merah)
        doc.layers.new(name='PERANGKAT_TITIK', dxfattribs={'color': 1})
        
        # Layer: LABEL_TEKS (warna 7 - putih/hitam)
        doc.layers.new(name='LABEL_TEKS', dxfattribs={'color': 7})
        
        # Hitung centroid untuk scaling
        if len(gdf) > 0:
            centroid = gdf.geometry.unary_union.centroid
            avg_x, avg_y = centroid.x, centroid.y
        else:
            avg_x, avg_y = 0, 0
        
        # 1. AMBIL DATA JALAN OSM (Opsional)
        road_count = 0
        if include_roads and len(gdf) > 0:
            try:
                with st.spinner("📡 Mengambil data jalan dari OpenStreetMap..."):
                    # Convert centroid ke (lat, lon) untuk OSM
                    centroid_latlon = (centroid.y, centroid.x)
                    
                    # Dapatkan graph dari OSM (area lebih kecil untuk performa)
                    G = ox.graph_from_point(
                        centroid_latlon, 
                        dist=500,  # Jarak 500m dari centroid
                        network_type='drive',
                        simplify=True
                    )
                    
                    # Convert ke GeoDataFrame
                    nodes, edges = ox.graph_to_gdfs(G)
                    
                    # Plot edges (jalan) ke DXF
                    for _, edge in edges.iterrows():
                        if hasattr(edge.geometry, 'geom_type') and edge.geometry.geom_type == 'LineString':
                            coords = list(edge.geometry.coords)
                            # Konversi koordinat (lon, lat) ke proyeksi DXF
                            # Scaling untuk menghindari koordinat yang terlalu kecil
                            scaled_coords = [(x, y) for x, y in coords]
                            msp.add_lwpolyline(
                                scaled_coords,
                                dxfattribs={'layer': 'MAP_JALAN'}
                            )
                            road_count += 1
                    
                    if road_count > 0:
                        st.sidebar.success(f"✅ {road_count} segmen jalan ditambahkan")
                    
            except Exception as e:
                st.sidebar.warning(f"⚠️ Data jalan tidak tersedia: {str(e)[:50]}...")
        
        # 2. PLOT DATA KML
        point_counter = 0
        line_counter = 0
        
        # Scaling factor untuk ukuran simbol yang konsisten
        scale_factor = 0.0001  # Diperbesar untuk visibilitas
        
        for idx, row in gdf.iterrows():
            geom = row.geometry
            name = str(row.get('Name', row.get('name', f'Obj_{idx+1}')))
            description = row.get('description', '')
            
            if geom.geom_type == 'Point':
                # Tambahkan titik sebagai circle dengan radius yang lebih besar
                radius = scale_factor * 5  # Radius lebih besar untuk visibilitas
                msp.add_circle(
                    center=(geom.x, geom.y),
                    radius=radius,
                    dxfattribs={'layer': 'PERANGKAT_TITIK'}
                )
                
                # Tambahkan label jika ada nama
                if name and name.lower() not in ['none', 'null', '', 'nan']:
                    # Buat text dengan height yang sesuai
                    text_height = scale_factor * 8
                    text = msp.add_text(
                        name,
                        dxfattribs={
                            'layer': 'LABEL_TEKS',
                            'height': text_height
                        }
                    )
                    # Posisikan text di atas titik
                    text.set_placement((geom.x, geom.y + radius * 2))
                
                point_counter += 1
                
            elif geom.geom_type == 'LineString':
                # Tambahkan polyline untuk LineString
                coords = list(geom.coords)
                msp.add_lwpolyline(
                    coords,
                    dxfattribs={'layer': 'KABEL_JARINGAN'}
                )
                line_counter += 1
        
        # 3. Tambahkan border dan informasi
        if len(gdf) > 0:
            # Tambahkan border rectangle
            bounds = gdf.total_bounds
            minx, miny, maxx, maxy = bounds
            
            # Rectangle border
            border_points = [
                (minx, miny),
                (maxx, miny),
                (maxx, maxy),
                (minx, maxy),
                (minx, miny)  # Close the rectangle
            ]
            
            msp.add_lwpolyline(
                border_points,
                dxfattribs={'layer': 'MAP_JALAN'}
            )
            
            # Tambahkan informasi metadata sebagai text
            info_text = f"KML to DXF - {point_counter+line_counter} objek"
            text_height = scale_factor * 10
            msp.add_text(
                info_text,
                dxfattribs={
                    'layer': 'LABEL_TEKS',
                    'height': text_height
                }
            ).set_placement((avg_x, miny - text_height * 3))
        
        # Simpan ke file temporary
        tmp_path = tempfile.mktemp(suffix='.dxf')
        doc.saveas(tmp_path)
        
        # Tampilkan statistik
        stats_text = f"""
        **📊 Statistik Konversi:**
        - Titik (Point): {point_counter}
        - Garis (LineString): {line_counter}
        - Jalan (OSM): {road_count}
        - **Total:** {point_counter + line_counter + road_count}
        """
        st.sidebar.markdown(stats_text)
        
        return tmp_path
        
    except Exception as e:
        st.error(f"❌ Gagal mengkonversi ke DXF: {str(e)}")
        import traceback
        st.error(f"Detail error: {traceback.format_exc()}")
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
    st.header("⚙️ Pengaturan")
    
    uploaded_file = st.file_uploader(
        "Upload file KML",
        type=['kml'],
        help="Upload file KML yang berisi data titik dan garis"
    )
    
    # Opsi konversi
    st.markdown("### Pengaturan Konversi")
    include_osm = st.checkbox(
        "Sertakan data jalan (OSM)",
        value=True,
        help="Tambah data jalan dari OpenStreetMap"
    )
    
    show_preview = st.checkbox(
        "Tampilkan preview peta",
        value=True,
        help="Tampilkan preview data di peta interaktif"
    )

# Main Content
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp:
        tmp.write(uploaded_file.getvalue())
        kml_path = tmp.name
    
    try:
        # Load KML
        with st.spinner("📂 Memproses file KML..."):
            gdf = load_kml_properly(kml_path)
            st.session_state.gdf = gdf
        
        if not gdf.empty and len(gdf) > 0:
            # Display statistics
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("#### 📍 Titik (Point)")
                point_count = len(gdf[gdf.geometry.type == 'Point'])
                st.metric("Jumlah", point_count)
            
            with col2:
                st.markdown("#### 📏 Garis (LineString)")
                line_count = len(gdf[gdf.geometry.type == 'LineString'])
                st.metric("Jumlah", line_count)
            
            with col3:
                st.markdown("#### 🏷️ Layer Sumber")
                layer_count = len(set(gdf.get('source_layer', ['Unknown'])))
                st.metric("Jumlah", layer_count)
            
            # Convert button
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("🚀 Generate DXF", type="primary", use_container_width=True):
                    with st.spinner("🔄 Mengkonversi ke format DXF..."):
                        dxf_path = convert_to_dxf_final(gdf, include_osm)
                        
                        if dxf_path and os.path.exists(dxf_path):
                            st.session_state.dxf_path = dxf_path
                            
                            # Show download button
                            with open(dxf_path, "rb") as f:
                                btn = st.download_button(
                                    label="📥 Download DXF",
                                    data=f,
                                    file_name="hasil_konversi.dxf",
                                    mime="application/dxf",
                                    type="primary",
                                    use_container_width=True
                                )
                            
                            if btn:
                                st.success("✅ File berhasil diunduh!")
            
            # Preview Map
            if show_preview:
                st.markdown("### 🗺️ Preview Peta")
                
                # Calculate map center
                center_lat = gdf.geometry.centroid.y.mean()
                center_lon = gdf.geometry.centroid.x.mean()
                
                # Create map
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=15,
                    tiles='OpenStreetMap',
                    control_scale=True
                )
                
                # Add points
                points_gdf = gdf[gdf.geometry.type == 'Point']
                for idx, row in points_gdf.iterrows():
                    popup_text = f"""
                    <b>Nama:</b> {row.get('Name', 'Tidak ada nama')}<br>
                    <b>Layer:</b> {row.get('source_layer', 'Unknown')}<br>
                    <b>Deskripsi:</b> {str(row.get('description', ''))[:100]}
                    """
                    
                    folium.CircleMarker(
                        location=[row.geometry.y, row.geometry.x],
                        radius=5,
                        color='red',
                        fill=True,
                        fill_color='red',
                        fill_opacity=0.7,
                        popup=folium.Popup(popup_text, max_width=300)
                    ).add_to(m)
                
                # Add lines
                lines_gdf = gdf[gdf.geometry.type == 'LineString']
                for idx, row in lines_gdf.iterrows():
                    coords = [(coord[1], coord[0]) for coord in row.geometry.coords]
                    
                    popup_text = f"""
                    <b>Tipe:</b> LineString<br>
                    <b>Layer:</b> {row.get('source_layer', 'Unknown')}<br>
                    <b>Panjang:</b> {row.geometry.length:.2f}°
                    """
                    
                    folium.PolyLine(
                        locations=coords,
                        color='blue',
                        weight=2,
                        opacity=0.8,
                        popup=folium.Popup(popup_text, max_width=300)
                    ).add_to(m)
                
                # Add tile layer control
                folium.TileLayer('Stamen Terrain').add_to(m)
                folium.TileLayer('CartoDB positron').add_to(m)
                folium.LayerControl().add_to(m)
                
                # Display map
                folium_static(m, width=1000, height=500)
            
            # Show data preview
            with st.expander("📋 Preview Data Raw"):
                # Tampilkan kolom yang ada
                available_cols = [col for col in gdf.columns if col not in ['geometry', 'source_layer']]
                if available_cols:
                    display_cols = ['source_layer'] + available_cols[:3]  # Tampilkan maksimal 3 kolom tambahan
                    st.dataframe(gdf[display_cols].head(20), use_container_width=True)
                else:
                    st.info("Tidak ada atribut tambahan dalam data")
        
        else:
            st.error("⚠️ File KML tidak berisi data Point atau LineString yang valid.")
            st.info("Pastikan file KML Anda berisi data titik (placemarks) atau garis (paths).")
            
    except Exception as e:
        st.error(f"❌ Terjadi kesalahan: {str(e)}")
        
    finally:
        # Cleanup temporary files
        if os.path.exists(kml_path):
            os.unlink(kml_path)

else:
    # Welcome/Instruction screen
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        ### Selamat Datang di KML to DXF Converter
        
        Aplikasi ini mengkonversi file KML (Google Earth/Maps) ke format DXF yang kompatibel dengan AutoCAD dan software CAD lainnya.
        
        #### 📋 Cara Penggunaan:
        1. **Upload** file KML melalui sidebar
        2. **Atur pengaturan** konversi (opsional)
        3. **Klik 'Generate DXF'** untuk memproses
        4. **Download** file hasil konversi
        
        #### ⚠️ Catatan Penting:
        - Hanya **Point** dan **LineString** yang dikonversi
        - Polygon akan diabaikan
        - Data jalan OSM bersifat opsional
        - Preview peta membantu verifikasi data
        
        #### 📁 Format yang Didukung:
        - **KML** (Keyhole Markup Language)
        - Data dari Google Earth/Maps
        - Ekspor dari QGIS/ArcGIS
        """)
    
    with col2:
        st.markdown("""
        #### 🎯 Contoh Data KML:
        
        **Struktur yang disarankan:**
        ```xml
        <Placemark>
          <name>Perangkat 1</name>
          <Point>
            <coordinates>106.123, -6.456, 0</coordinates>
          </Point>
        </Placemark>
        
        <Placemark>
          <name>Jalur Kabel</name>
          <LineString>
            <coordinates>
              106.123,-6.456,0
              106.124,-6.457,0
            </coordinates>
          </LineString>
        </Placemark>
        ```
        """)

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.9em;'>"
    "KML to DXF Converter • v2.1 • "
    "© 2024 • Support: AutoCAD R2010+"
    "</div>",
    unsafe_allow_html=True
)
