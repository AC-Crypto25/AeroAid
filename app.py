import streamlit as st
import pandas as pd
import math
import numpy as np
import pydeck as pdk
import requests

# --- 1. CONFIGURATION & CUSTOM CSS ---
st.set_page_config(page_title="AeroAid Pro: Level D EFB", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stApp { background-color: #0b0f19; color: #00ff00; font-family: 'Courier New', Courier, monospace; }
    .pfd-card { background-color: #161b22; border: 2px solid #00ff00; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 0 10px rgba(0, 255, 0, 0.2); }
    .pfd-warning { border-color: #ff9900; box-shadow: 0 0 15px rgba(255, 153, 0, 0.4); color: #ff9900; }
    .pfd-critical { border-color: #ff0000; box-shadow: 0 0 15px rgba(255, 0, 0, 0.6); color: #ff0000; }
    h1, h2, h3, h4 { color: #00ff00; }
    .stTabs [data-baseweb="tab-list"] { background-color: #161b22; border-radius: 8px; padding: 5px; }
    .stTabs [data-baseweb="tab"] { color: #00ff00; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide_max": 210, "empty_wt": 90000, "max_fuel": 46000},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide_max": 230, "empty_wt": 370000, "max_fuel": 320000},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide_max": 220, "empty_wt": 284000, "max_fuel": 223000},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide_max": 200, "empty_wt": 94000, "max_fuel": 42000},
}

AIRLINES = ["American Airlines", "British Airways", "Delta Air Lines", "Emirates", "Lufthansa", "Qantas", "Singapore Airlines", "United Airlines"]
EMERGENCIES = ["Dual Engine Failure", "Single Engine Failure", "Rapid Depressurization", "Hydraulic System Loss", "Electrical Smoke/Fire"]

@st.cache_data
def load_airports():
    df = pd.read_csv("https://davidmegginson.github.io/ourairports-data/airports.csv")
    df = df[df['type'] != 'closed'].copy()
    return df.dropna(subset=['iso_country', 'municipality', 'name', 'latitude_deg', 'longitude_deg', 'ident'])

@st.cache_data
def load_runways():
    df = pd.read_csv("https://davidmegginson.github.io/ourairports-data/runways.csv")
    hard_surfaces = ['ASP', 'CON', 'ASPH', 'CONC', 'MAC', 'PEM']
    df = df[df['surface'].astype(str).str.upper().isin(hard_surfaces)]
    df['le_heading_degT'] = pd.to_numeric(df['le_heading_degT'], errors='coerce')
    return df

@st.cache_data
def load_frequencies():
    return pd.read_csv("https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv")

all_airports = load_airports()
all_runways = load_runways()
all_freqs = load_frequencies()

# --- 2. ADVANCED MATH & LIVE APIs ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def check_notam_closure(icao, api_key):
    """Hits the FAA NOTAM API to search for runway closures."""
    if not api_key: 
        return False # Bypass if no key provided by user
        
    url = f"https://external-api.faa.gov/notamapi/v1/notams?icaoLocation={icao}"
    headers = {"client_id": api_key}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            notams = response.json().get('items', [])
            for notam in notams:
                text = notam.get('properties', {}).get('coreNOTAMData', {}).get('notamText', '').upper()
                if "RWY CLSD" in text or "RUNWAY CLOSED" in text:
                    return True # Hard failure - runway is closed
    except Exception as e:
        st.sidebar.error(f"NOTAM API Error: {e}")
    return False

def generate_terrain_masked_ring(center_lat, center_lon, radius_nm, ac_alt_ft, points=36):
    """Uses OpenTopoData API to explicitly mask the glide ring based on MSA."""
    ring = []
    lat_deg_per_nm = 1 / 60.0
    lon_deg_per_nm = 1 / (60.0 * math.cos(math.radians(center_lat)))
    
    coords = []
    for i in range(points):
        angle = math.radians(float(i) / points * 360.0)
        d_lat = radius_nm * math.cos(angle) * lat_deg_per_nm
        d_lon = radius_nm * math.sin(angle) * lon_deg_per_nm
        coords.append((center_lat + d_lat, center_lon + d_lon))
    
    # Live elevation query
    locations_str = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://api.opentopodata.org/v1/srtm90m?locations={locations_str}"
    
    try:
        response = requests.get(url, timeout=10)
        elev_data = response.json().get('results', [])
        
        for i, res in enumerate(elev_data):
            elev_meters = res.get('elevation', 0)
            elev_ft = elev_meters * 3.28084 if elev_meters else 0
            
            # If terrain eats the 1,000ft safety buffer, crush the glide ring on this vector
            if elev_ft > (ac_alt_ft - 1000):
                mod_radius = radius_nm * 0.2 # Massive penalty for terrain intersection
                d_lat = mod_radius * math.cos(math.radians(float(i) / points * 360.0)) * lat_deg_per_nm
                d_lon = mod_radius * math.sin(math.radians(float(i) / points * 360.0)) * lon_deg_per_nm
                ring.append([center_lon + d_lon, center_lat + d_lat])
            else:
                ring.append([coords[i][1], coords[i][0]])
    except Exception as e:
        st.error(f"TERRAIN API FAILURE: {e}. Defaulting to unmasked ring.")
        for lat, lon in coords:
            ring.append([lon, lat])
            
    return [ring]

def calculate_time_to_impact(distance_nm, groundspeed_kts):
    if groundspeed_kts <= 0: return "N/A"
    time_hours = distance_nm / groundspeed_kts
    return f"{int(time_hours * 60):02d}:{int((time_hours * 60 % 1) * 60):02d}"

# --- 3. UI: SIDEBAR INPUTS ---
st.title("✈️ AeroAid Pro: EFB Level D")

with st.sidebar:
    st.header("1. Flight Status")
    airline = st.selectbox("Airline Operator", AIRLINES)
    ac_type = st.selectbox("Aircraft", list(AIRCRAFT_DATA.keys()))
    fuel_pct = st.slider("Current Fuel %", 0, 100, 50)
    
    st.markdown("---")
    st.header("🚨 FAILURES & ENVIRONMENT")
    active_emergencies = st.multiselect("Active Failures", EMERGENCIES, default=["Dual Engine Failure"])
    icing_conditions = st.checkbox("❄️ Icing Conditions (Anti-Ice ON)", value=False)
    
    st.markdown("---")
    st.header("🔑 ENTERPRISE APIs")
    faa_api_key = st.text_input("FAA NOTAM API Key", type="password", help="Leave blank to bypass NOTAM check.")
    
    st.markdown("---")
    st.header("2. Position Data")
    search_clue = st.text_input("City/Clue Search", "Denver")
    
    search_results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False, na=False) | 
        all_airports['municipality'].str.contains(search_clue, case=False, na=False) |
        all_airports['ident'].str.contains(search_clue, case=False, na=False)
    ]
    
    if not search_results.empty:
        first_row = search_results.iloc[0]
        found_lat, found_lon = float(first_row['latitude_deg']), float(first_row['longitude_deg'])
        st.success(f"📍 GPS Lock: {first_row['ident']}")
    else:
        found_lat, found_lon = 0.0, 0.0

    lat = st.number_input("Latitude", value=found_lat, format="%.4f")
    lon = st.number_input("Longitude", value=found_lon, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=25000, step=1000)

# --- AIRCRAFT PERFORMANCE & DEGRADATION LOGIC ---
ac = AIRCRAFT_DATA[ac_type]
current_wt = ac['empty_wt'] + (ac['max_fuel'] * (fuel_pct / 100))
max_wt = ac['empty_wt'] + ac['max_fuel']

v_glide = ac['v_glide_max'] * math.sqrt(current_wt / max_wt)
effective_glide_ratio = ac['glide_ratio'] * 0.7
effective_alt = max(alt - 1500, 0)

if "Hydraulic System Loss" in active_emergencies:
    effective_glide_ratio *= 0.85
if icing_conditions:
    effective_glide_ratio *= 0.75 
    v_glide += 10 

max_glide_nm = (effective_alt / 6076) * effective_glide_ratio
v_ref = v_glide * 0.7

st.sidebar.markdown("---")
st.sidebar.metric("ESTIMATED V-REF (FLAPS FULL)", f"{int(v_ref)} KTS")

# --- GLOBAL AIRPORT FILTERING & LIVE NOTAM CHECK ---
valid_runways = all_runways[all_runways['length_ft'] >= ac['min_runway']]
valid_airport_idents = valid_runways['airport_ident'].unique()

calc_df = all_airports[all_airports['ident'].isin(valid_airport_idents)].copy()
calc_df['distance'] = calc_df.apply(lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1)

ranked_airports = calc_df.sort_values('distance')
top_apt = None

with st.spinner("Ping FAA API for NOTAMs..."):
    for _, apt in ranked_airports.iterrows():
        # Executes the live check against the actual API
        if not check_notam_closure(apt['ident'], faa_api_key):
            top_apt = apt
            break

if top_apt is None:
    st.error("SYSTEM FAILURE: No open runways found. All nearby valid airports have RWY CLSD NOTAMs.")
    st.stop()

# --- GOLDEN RULE UI SPLIT ---
tab_aviate, tab_navigate, tab_communicate = st.tabs(["⚠️ PRIMARY FLIGHT (AVIATE)", "🗺️ AIRPORT & VNAV (NAVIGATE)", "📻 CHECKLISTS & COMMS (COMMUNICATE)"])

# ==========================================
# TAB 1: AVIATE
# ==========================================
with tab_aviate:
    st.error(f"🚨 MASTER CAUTION: {len(active_emergencies)} FAILURES DETECTED")
    st.markdown("<div class='pfd-card'>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    col1.metric("TARGET V-GLIDE", f"{int(v_glide)} KTS", delta="+10 ICE" if icing_conditions else None, delta_color="inverse")
    col2.metric("MAX GLIDE RANGE", f"{round(max_glide_nm, 1)} NM")
    col3.metric("REACTION ALTITUDE", f"{int(effective_alt)} FT")
    
    if current_wt > (ac['empty_wt'] * 1.4):
        st.markdown(f"<span style='color:#ff0000;'><b>⚠️ OVERWEIGHT LANDING:</b> Weight ({int(current_wt):,} lbs) exceeds MLW.</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### ⚡ IMMEDIATE ACTION ITEMS")
    checklist_html = "<div class='pfd-card pfd-critical' style='font-size: 1.2rem; line-height: 1.8;'>"
    if "Dual Engine Failure" in active_emergencies or "Single Engine Failure" in active_emergencies:
        checklist_html += "<b>➔ PITCH:</b> MAINTAIN V-GLIDE<br><b>➔ GEAR/FLAPS:</b> UP<br>"
    if "Rapid Depressurization" in active_emergencies:
        checklist_html += "<b>➔ OXYGEN MASKS:</b> ON / 100%<br><b>➔ EMERGENCY DESCENT:</b> INITIATE TO 10,000 FT<br>"
    if icing_conditions:
        checklist_html += "<b>➔ ENGINE/WING ANTI-ICE:</b> MAX / OVERRIDE<br>"
    checklist_html += "</div>"
    st.markdown(checklist_html, unsafe_allow_html=True)

# ==========================================
# TAB 2: NAVIGATE
# ==========================================
with tab_navigate:
    st.subheader(f"TARGET: {top_apt['name']} ({top_apt['ident']})")
    tti_str = calculate_time_to_impact(top_apt['distance'], v_glide)

    col_v1, col_v2 = st.columns(2)
    col_v1.metric("DIST TO FIELD", f"{round(top_apt['distance'], 1)} NM")
    col_v2.metric("TIME TO IMPACT", tti_str)
    
    field_elevation = top_apt.get('elevation_ft', 0) if not pd.isna(top_apt.get('elevation_ft', 0)) else 0
    glide_gradient = 6076 / effective_glide_ratio 

    st.markdown("### 📉 VERTICAL PROFILE (VNAV)")
    dist_steps = np.linspace(top_apt['distance'], 0, 10)
    required_alt_profile = (dist_steps * glide_gradient) + field_elevation
    actual_alt_profile = np.linspace(effective_alt, field_elevation, 10)

    chart_df = pd.DataFrame({
        "Distance to Field (NM)": dist_steps,
        "Glide Path (Required)": required_alt_profile,
        "Your Profile (Projected)": actual_alt_profile
    }).set_index("Distance to Field (NM)")

    st.area_chart(chart_df, color=["#ff0000", "#00ff00"])
    
    st.markdown("### 🌍 SITUATIONAL AWARENESS DISPLAY (SAD)")
    with st.spinner("Masking Terrain Data..."):
        glide_ring_coords = generate_terrain_masked_ring(lat, lon, max_glide_nm, alt)

    view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=8, pitch=30)
    st.pydeck_chart(pdk.Deck(
        map_style='mapbox://styles/mapbox/dark-v10',
        layers=[
            pdk.Layer("PolygonLayer", data=[{"polygon": glide_ring_coords[0]}], get_polygon="polygon", get_fill_color="[0, 255, 0, 30]", get_line_color="[0, 255, 0, 200]", line_width_min_pixels=3),
            pdk.Layer("ScatterplotLayer", data=[{"lat": float(top_apt['latitude_deg']), "lon": float(top_apt['longitude_deg'])}], get_position="[lon, lat]", get_color="[0, 255, 0, 200]", get_radius=1200, radius_min_pixels=8),
            pdk.Layer("ScatterplotLayer", data=[{"lat": lat, "lon": lon}], get_position="[lon, lat]", get_color="[255, 255, 255, 255]", get_radius=800, radius_min_pixels=6)
        ], 
        initial_view_state=view_state
    ))

# ==========================================
# TAB 3: COMMUNICATE
# ==========================================
with tab_communicate:
    st.markdown("### 📻 ATC DATALINK FREQUENCIES")
    target_freqs = all_freqs[all_freqs['airport_ident'] == top_apt['ident']]

    if not target_freqs.empty:
        freq_html = "<div class='pfd-card'><div style='display: flex; flex-wrap: wrap; gap: 20px;'>"
        for _, row in target_freqs.iterrows():
            f_type = str(row['type']).upper()
            f_mhz = row['frequency_mhz']
            f_desc = str(row['description']).title() if not pd.isna(row['description']) else f_type
            color = "#ff9900" if "TWR" in f_type or "APP" in f_type else "#00ff00"
                
            freq_html += f"<div style='border-left: 3px solid {color}; padding-left: 10px;'>"
            freq_html += f"<span style='color: {color}; font-weight: bold;'>{f_mhz}</span><br>"
            freq_html += f"<span style='font-size: 0.9em;'>{f_desc}</span></div>"
        freq_html += "</div></div>"
        st.markdown(freq_html, unsafe_allow_html=True)
    else:
        st.markdown("<div class='pfd-card pfd-warning'>⚠️ NO LOCAL ATC PUBLISHED. TRANSMIT ON 121.500 (GUARD).</div>", unsafe_allow_html=True)
        
    st.markdown("### 📋 SECONDARY NON-NORMAL CHECKLISTS")
    st.markdown("""
    <div class='pfd-card'>
        <ul>
            <li><b>TRANSPONDER:</b> SQUAWK 7700</li>
            <li><b>MAYDAY CALL:</b> "MAYDAY, MAYDAY, MAYDAY. [Callsign] HAS EXPERIENCED [Emergency]. INTENTIONS TO DIVERT TO [Target Field]."</li>
            <li><b>CABIN CREW:</b> NOTIFY "BRACE FOR IMPACT" PREPARATIONS.</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
