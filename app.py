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
    .metric-card {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        border-left: 4px solid #007bff;
        margin-bottom: 10px;
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
            
            # Tambahkan ID unik untuk setiap fitur
            full_gdf['feature_id'] = range(1, len(full_gdf) + 1)
            
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
        
        # Scaling factor yang lebih tepat untuk koordinat geografis
        scale_factor = 1.0  # Tidak perlu scaling untuk koordinat asli
        point_size = 0.001  # Ukuran titik dalam derajat
        text_height = 0.0005  # Tinggi teks dalam derajat
        
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
                        dist=300,  # Jarak 300m dari centroid
                        network_type='drive',
                        simplify=True
                    )
                    
                    # Convert ke GeoDataFrame
                    nodes, edges = ox.graph_to_gdfs(G)
                    
                    # Plot edges (jalan) ke DXF
                    for _, edge in edges.iterrows():
                        if hasattr(edge.geometry, 'geom_type') and edge.geometry.geom_type == 'LineString':
                            coords = list(edge.geometry.coords)
                            msp.add_lwpolyline(
                                coords,
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
        
        for idx, row in gdf.iterrows():
            geom = row.geometry
            feature_id = row.get('feature_id', idx + 1)
            name = str(row.get('Name', row.get('name', f'ID-{feature_id}')))
            
            if geom.geom_type == 'Point':
                # Tambahkan titik sebagai circle
                radius = point_size
                msp.add_circle(
                    center=(geom.x, geom.y),
                    radius=radius,
                    dxfattribs={'layer': 'PERANGKAT_TITIK'}
                )
                
                # Tambahkan label jika ada nama
                if name and name.lower() not in ['none', 'null', '', 'nan']:
                    text = msp.add_text(
                        name,
                        dxfattribs={
                            'layer': 'LABEL_TEKS',
                            'height': text_height
                        }
                    )
                    # Posisikan text di atas titik
                    text.set_placement((geom.x, geom.y + radius * 3))
                
                point_counter += 1
                
            elif geom.geom_type == 'LineString':
                # Tambahkan polyline untuk LineString
                coords = list(geom.coords)
                msp.add_lwpolyline(
                    coords,
                    dxfattribs={'layer': 'KABEL_JARINGAN'}
                )
                line_counter += 1
        
        # 3. Tambahkan informasi metadata sebagai text
        if len(gdf) > 0:
            # Tambahkan informasi proyek
            info_text = f"KML to DXF - {point_counter}P/{line_counter}L - {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
            msp.add_text(
                info_text,
                dxfattribs={
                    'layer': 'LABEL_TEKS',
                    'height': text_height * 2
                }
            ).set_placement((avg_x, avg_y - text_height * 10))
        
        # Simpan ke file temporary
        tmp_path = tempfile.mktemp(suffix='.dxf')
        doc.saveas(tmp_path)
        
        # Tampilkan statistik
        stats_text = f"""
        **📊 Statistik Konversi:**
        - Titik (Point): {point_counter}
        - Garis (LineString): {line_counter}
        - Jalan (OSM): {road_count}
        - **Total Objek:** {point_counter + line_counter + road_count}
        """
        st.sidebar.markdown(stats_text)
        
        return tmp_path
        
    except Exception as e:
        st.error(f"❌ Gagal mengkonversi ke DXF: {str(e)}")
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
    
    # Informasi bantuan
    with st.expander("ℹ️ Tips"):
        st.markdown("""
        1. Pastikan file KML berisi **Point** atau **LineString**
        2. Data jalan OMS otomatis mengambil area 300m
        3. Hasil DXF memiliki 4 layer terpisah
        4. Koordinat tetap dalam WGS84 (derajat)
        """)

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
            # Display statistics in cards
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                point_count = len(gdf[gdf.geometry.type == 'Point'])
                st.markdown("#### 📍 Titik (Point)")
                st.markdown(f"### {point_count}")
                st.markdown("objek")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                line_count = len(gdf[gdf.geometry.type == 'LineString'])
                st.markdown("#### 📏 Garis (LineString)")
                st.markdown(f"### {line_count}")
                st.markdown("objek")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                layer_count = len(set(gdf.get('source_layer', ['Unknown'])))
                st.markdown("#### 🏷️ Layer Sumber")
                st.markdown(f"### {layer_count}")
                st.markdown("layer")
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Bounding box info
            bounds = gdf.total_bounds
            st.info(f"**Area Data:** Latitude: {bounds[1]:.6f}° - {bounds[3]:.6f}° | Longitude: {bounds[0]:.6f}° - {bounds[2]:.6f}°")
            
            # Convert button
            st.markdown("---")
            col1, col2 = st.columns([1, 1])
            
            with col1:
                if st.button("🚀 Generate DXF File", type="primary", use_container_width=True):
                    with st.spinner("🔄 Mengkonversi ke format DXF..."):
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
            
            with col2:
                if st.button("🔄 Reset Preview", use_container_width=True):
                    st.rerun()
            
            # Preview Map
            if show_preview:
                st.markdown("### 🗺️ Preview Peta")
                
                # Calculate map center
                center_lat = gdf.geometry.centroid.y.mean()
                center_lon = gdf.geometry.centroid.x.mean()
                
                # Create map with OpenStreetMap as default
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=15,
                    tiles='OpenStreetMap',
                    attr='OpenStreetMap contributors',
                    control_scale=True
                )
                
                # Add Google Satellite layer (with proper attribution)
                google_satellite = folium.TileLayer(
                    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                    attr='Google',
                    name='Google Satellite',
                    overlay=False,
                    control=True
                )
                google_satellite.add_to(m)
                
                # Add Google Hybrid layer
                google_hybrid = folium.TileLayer(
                    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
                    attr='Google',
                    name='Google Hybrid',
                    overlay=False,
                    control=True
                )
                google_hybrid.add_to(m)
                
                # Add CartoDB layer
                cartodb = folium.TileLayer(
                    tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
                    attr='CartoDB',
                    name='CartoDB Light',
                    overlay=False,
                    control=True
                )
                cartodb.add_to(m)
                
                # Group untuk fitur KML
                feature_group = folium.FeatureGroup(name='Data KML', overlay=True)
                
                # Add points
                points_gdf = gdf[gdf.geometry.type == 'Point']
                for idx, row in points_gdf.iterrows():
                    feature_id = row.get('feature_id', idx + 1)
                    name = row.get('Name', row.get('name', f'ID-{feature_id}'))
                    layer_name = row.get('source_layer', 'Unknown')
                    
                    popup_text = f"""
                    <div style="font-family: Arial, sans-serif;">
                        <h4 style="margin: 0 0 10px 0;">{name}</h4>
                        <p style="margin: 2px 0;"><b>ID:</b> {feature_id}</p>
                        <p style="margin: 2px 0;"><b>Layer:</b> {layer_name}</p>
                        <p style="margin: 2px 0;"><b>Tipe:</b> Point</p>
                        <p style="margin: 2px 0;"><b>Koordinat:</b><br>
                        Lat: {row.geometry.y:.6f}°<br>
                        Lon: {row.geometry.x:.6f}°
                        </p>
                    </div>
                    """
                    
                    folium.CircleMarker(
                        location=[row.geometry.y, row.geometry.x],
                        radius=6,
                        color='#FF0000',
                        fill=True,
                        fill_color='#FF0000',
                        fill_opacity=0.7,
                        weight=2,
                        popup=folium.Popup(popup_text, max_width=300),
                        tooltip=f"{name} (ID: {feature_id})"
                    ).add_to(feature_group)
                
                # Add lines
                lines_gdf = gdf[gdf.geometry.type == 'LineString']
                for idx, row in lines_gdf.iterrows():
                    feature_id = row.get('feature_id', idx + 1)
                    name = row.get('Name', row.get('name', f'Line-{feature_id}'))
                    layer_name = row.get('source_layer', 'Unknown')
                    
                    coords = [(coord[1], coord[0]) for coord in row.geometry.coords]
                    
                    popup_text = f"""
                    <div style="font-family: Arial, sans-serif;">
                        <h4 style="margin: 0 0 10px 0;">{name}</h4>
                        <p style="margin: 2px 0;"><b>ID:</b> {feature_id}</p>
                        <p style="margin: 2px 0;"><b>Layer:</b> {layer_name}</p>
                        <p style="margin: 2px 0;"><b>Tipe:</b> LineString</p>
                        <p style="margin: 2px 0;"><b>Panjang:</b> {row.geometry.length:.3f}°</p>
                        <p style="margin: 2px 0;"><b>Vertex:</b> {len(row.geometry.coords)} titik</p>
                    </div>
                    """
                    
                    folium.PolyLine(
                        locations=coords,
                        color='#0000FF',
                        weight=3,
                        opacity=0.8,
                        popup=folium.Popup(popup_text, max_width=300),
                        tooltip=f"{name} (Line)"
                    ).add_to(feature_group)
                
                # Add feature group to map
                feature_group.add_to(m)
                
                # Add layer control
                folium.LayerControl(collapsed=False).add_to(m)
                
                # Add fullscreen button
                folium.plugins.Fullscreen().add_to(m)
                
                # Display map
                folium_static(m, width=1000, height=600)
            
            # Show data preview
            with st.expander("📋 Detail Data"):
                tab1, tab2 = st.tabs(["📊 Tabel Data", "📈 Informasi Layer"])
                
                with tab1:
                    # Tampilkan kolom yang ada
                    available_cols = [col for col in gdf.columns if col not in ['geometry']]
                    if available_cols:
                        # Pilih kolom untuk ditampilkan
                        default_cols = ['feature_id', 'source_layer', 'Name', 'name', 'description']
                        display_cols = [col for col in default_cols if col in available_cols]
                        
                        if not display_cols:  # Jika tidak ada kolom default, ambil 3 kolom pertama
                            display_cols = available_cols[:3]
                        
                        st.dataframe(
                            gdf[display_cols].head(50),
                            use_container_width=True,
                            height=300
                        )
                        
                        # Tampilkan total data
                        st.caption(f"Menampilkan 50 dari {len(gdf)} baris data")
                    else:
                        st.info("Tidak ada atribut tambahan dalam data")
                
                with tab2:
                    # Statistik per layer
                    layer_stats = gdf.groupby('source_layer').agg({
                        'feature_id': 'count',
                        'geometry': lambda x: x.type.iloc[0] if len(x) > 0 else 'Unknown'
                    }).reset_index()
                    
                    layer_stats.columns = ['Layer', 'Jumlah Objek', 'Tipe Dominan']
                    st.dataframe(layer_stats, use_container_width=True)
                    
                    # Pie chart sederhana untuk distribusi layer
                    if len(layer_stats) > 0:
                        st.markdown("**Distribusi Objek per Layer:**")
                        for _, row in layer_stats.iterrows():
                            percentage = (row['Jumlah Objek'] / len(gdf)) * 100
                            st.progress(percentage/100, text=f"{row['Layer']}: {row['Jumlah Objek']} objek ({percentage:.1f}%)")
        
        else:
            st.error("⚠️ File KML tidak berisi data Point atau LineString yang valid.")
            st.info("""
            **Kemungkinan masalah:**
            1. File hanya berisi Polygon (tidak dikonversi)
            2. File KML kosong
            3. Format file tidak sesuai
            
            **Solusi:**
            - Pastikan file berisi Placemark dengan tipe Point atau LineString
            - Coba ekspor ulang dari Google Earth/Maps
            - Periksa struktur file KML
            """)
            
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
        ### 🎯 KML to DXF Converter
        
        Alat profesional untuk mengkonversi file KML (Google Earth/Maps) ke format DXF yang kompatibel dengan AutoCAD dan software CAD lainnya.
        
        #### 🚀 Cara Menggunakan:
        1. **Upload File** - Pilih file KML melalui sidebar di kiri
        2. **Atur Pengaturan** - Pilih opsi konversi yang diinginkan
        3. **Generate DXF** - Klik tombol untuk memproses konversi
        4. **Download** - Unduh file DXF hasil konversi
        
        #### 📁 Format Input:
        - **KML** (Keyhole Markup Language)
        - Data dari Google Earth
        - Ekspor dari Google Maps
        - Hasil dari QGIS/ArcGIS
        
        #### 🎨 Output DXF:
        - 4 Layer terorganisir
        - Warna yang berbeda per tipe data
        - Label teks untuk identifikasi
        - Koordinat presisi tinggi
        """)
    
    with col2:
        st.markdown("""
        #### 🔧 Layer Output:
        
        **1. MAP_JALAN** (Abu-abu)
        - Data jalan dari OSM
        
        **2. KABEL_JARINGAN** (Hijau)
        - LineString dari KML
        
        **3. PERANGKAT_TITIK** (Merah)
        - Point dari KML
        
        **4. LABEL_TEKS** (Putih/Hitam)
        - Label dan informasi
        
        #### ⚡ Fitur Unggulan:
        - Preview peta interaktif
        - Auto-fetch data jalan
        - Multi-layer support
        - Statistik detail
        - Clean interface
        """)

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.9em;'>"
    "🛠️ KML to DXF Professional Converter • Version 2.2 • "
    "© 2024 • Compatible with AutoCAD R2010+"
    "</div>",
    unsafe_allow_html=True
)
