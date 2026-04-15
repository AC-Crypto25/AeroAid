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
    df['he_heading_degT'] = pd.to_numeric(df['he_heading_degT'], errors='coerce')
    df['length_ft'] = pd.to_numeric(df['length_ft'], errors='coerce')
    return df.dropna(subset=['length_ft'])

@st.cache_data
def load_frequencies():
    return pd.read_csv("https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv")

all_airports = load_airports()
all_runways = load_runways()
all_freqs = load_frequencies()

# --- 2. ADVANCED MATH & IDEAL PATH LOGIC ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_live_metar(icao):
    """Fetches the absolute latest weather report for wind alignment calculation."""
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=1"
        response = requests.get(url, timeout=3)
        data = response.json()
        if data: return {"wdir": data[0].get("wdir", 0), "wspd": data[0].get("wspd", 0)}
    except: return None
    return {"wdir": 0, "wspd": 0} # Fallback to calm winds if API fails

def score_airport(distance, max_glide, runways_df, wind_dir, wind_spd, ac_min_rwy):
    """
    The Suitability Matrix: Scores airports out of 100 based on survivability.
    """
    score = 100.0
    best_rwy = None
    best_hw_comp = -999
    max_len_found = 0

    # 1. Energy Margin Penalty (If it's at the absolute edge of glide, it's risky)
    glide_ratio_used = distance / max_glide
    if glide_ratio_used > 0.85: score -= 30  # High risk of falling short
    elif glide_ratio_used < 0.2: score -= 10 # Too close, high energy management required
    else: score += 10 # Ideal energy margin

    # 2. Evaluate Runways for Length and Wind Alignment
    for _, rwy in runways_df.iterrows():
        rwy_len = rwy['length_ft']
        
        # Check both ends of the runway
        for hdg_col, ident_col in [('le_heading_degT', 'le_ident'), ('he_heading_degT', 'he_ident')]:
            if not pd.isna(rwy[hdg_col]):
                rwy_hdg = rwy[hdg_col]
                
                # Wind calculation
                angle_diff = math.radians(wind_dir - rwy_hdg)
                headwind = wind_spd * math.cos(angle_diff)
                crosswind = abs(wind_spd * math.sin(angle_diff))
                
                # We want maximum headwind, minimum crosswind, maximum length
                rwy_score = 0
                rwy_score += (rwy_len - ac_min_rwy) / 100  # Bonus for extra length
                rwy_score += headwind * 2                  # Bonus for headwind
                rwy_score -= crosswind * 3                 # Severe penalty for crosswind
                
                if rwy_score > best_hw_comp:
                    best_hw_comp = rwy_score
                    best_rwy = rwy[ident_col]
                    max_len_found = rwy_len

    # Apply best runway stats to total airport score
    score += best_hw_comp
    
    return score, best_rwy, max_len_found

# --- 3. UI: SIDEBAR INPUTS ---
st.title("✈️ AeroAid Pro: Level D (Survival Protocol)")

with st.sidebar:
    st.header("1. Flight Status")
    ac_type = st.selectbox("Aircraft", list(AIRCRAFT_DATA.keys()))
    fuel_pct = st.slider("Current Fuel %", 0, 100, 50)
    
    st.markdown("---")
    st.header("🚨 FAILURES & ENVIRONMENT")
    active_emergencies = st.multiselect("Active Failures", EMERGENCIES, default=["Dual Engine Failure"])
    icing_conditions = st.checkbox("❄️ Icing Conditions (Anti-Ice ON)", value=False)
    
    st.markdown("---")
    st.header("2. Position Data")
    search_clue = st.text_input("City/Clue Search", "Denver")
    
    search_results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False, na=False) | 
        all_airports['ident'].str.contains(search_clue, case=False, na=False)
    ]
    
    if not search_results.empty:
        found_lat, found_lon = float(search_results.iloc[0]['latitude_deg']), float(search_results.iloc[0]['longitude_deg'])
        st.success(f"📍 GPS Lock: {search_results.iloc[0]['ident']}")
    else:
        found_lat, found_lon = 0.0, 0.0

    lat = st.number_input("Latitude", value=found_lat, format="%.4f")
    lon = st.number_input("Longitude", value=found_lon, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=30000, step=1000)

# --- AIRCRAFT PERFORMANCE LOGIC ---
ac = AIRCRAFT_DATA[ac_type]
current_wt = ac['empty_wt'] + (ac['max_fuel'] * (fuel_pct / 100))
max_wt = ac['empty_wt'] + ac['max_fuel']

v_glide = ac['v_glide_max'] * math.sqrt(current_wt / max_wt)
effective_glide_ratio = ac['glide_ratio'] * 0.7
effective_alt = max(alt - 1500, 0)

if "Hydraulic System Loss" in active_emergencies: effective_glide_ratio *= 0.85
if icing_conditions: 
    effective_glide_ratio *= 0.75 
    v_glide += 10 

max_glide_nm = (effective_alt / 6076) * effective_glide_ratio
v_ref = v_glide * 0.7

# --- THE "IDEAL" AIRPORT SELECTION ---
valid_runways = all_runways[all_runways['length_ft'] >= ac['min_runway']]
valid_airport_idents = valid_runways['airport_ident'].unique()

calc_df = all_airports[all_airports['ident'].isin(valid_airport_idents)].copy()
calc_df['distance'] = calc_df.apply(lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1)

# Filter out airports beyond absolute max glide
reachable_airports = calc_df[calc_df['distance'] <= max_glide_nm].copy()

if reachable_airports.empty:
    st.error("SYSTEM FAILURE: NO REACHABLE HARD-SURFACE RUNWAYS. PREPARE FOR OFF-FIELD LANDING/DITCHING.")
    st.stop()

# Evaluate the Suitability Score for all reachable airports
scored_airports = []
with st.spinner("Calculating Suitability Matrix & Fetching Live Weather..."):
    for _, apt in reachable_airports.iterrows():
        apt_runways = valid_runways[valid_runways['airport_ident'] == apt['ident']]
        wx = get_live_metar(apt['ident'])
        
        score, best_rwy, best_len = score_airport(
            apt['distance'], max_glide_nm, apt_runways, 
            wx['wdir'], wx['wspd'], ac['min_runway']
        )
        scored_airports.append({
            "apt_data": apt, "score": score, "best_rwy": best_rwy, 
            "rwy_len": best_len, "wx": wx
        })

# Sort by highest survivability score, not closest distance
scored_airports.sort(key=lambda x: x['score'], reverse=True)
ideal_target = scored_airports[0]
top_apt = ideal_target['apt_data']

# --- GOLDEN RULE UI SPLIT ---
tab_aviate, tab_navigate, tab_communicate = st.tabs(["⚠️ PRIMARY FLIGHT (AVIATE)", "🗺️ ROUTING & ENERGY (NAVIGATE)", "📻 COMMS (COMMUNICATE)"])

# ==========================================
# TAB 1: AVIATE
# ==========================================
with tab_aviate:
    st.error(f"🚨 MASTER CAUTION: {len(active_emergencies)} FAILURES DETECTED")
    st.markdown("<div class='pfd-card'>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    col1.metric("TARGET V-GLIDE", f"{int(v_glide)} KTS")
    col2.metric("MAX GLIDE RANGE", f"{round(max_glide_nm, 1)} NM")
    col3.metric("REACTION ALTITUDE", f"{int(effective_alt)} FT")
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
# TAB 2: NAVIGATE (ENERGY MANAGEMENT)
# ==========================================
with tab_navigate:
    st.subheader(f"IDEAL TARGET: {top_apt['name']} ({top_apt['ident']})")
    
    wx = ideal_target['wx']
    st.info(f"📡 WEATHER DATALINK: Wind {wx['wdir']:03d}° at {wx['wspd']} KTS | Ideal Runway: {ideal_target['best_rwy']} ({int(ideal_target['rwy_len'])} FT)")
    
    # High Key Logic (Aiming 3000ft above the field, not the runway threshold)
    field_elevation = top_apt.get('elevation_ft', 0) if not pd.isna(top_apt.get('elevation_ft', 0)) else 0
    high_key_alt = field_elevation + 3000
    glide_gradient = 6076 / effective_glide_ratio 
    
    alt_needed_for_straight_in = (top_apt['distance'] * glide_gradient) + field_elevation
    excess_energy = effective_alt - alt_needed_for_straight_in
    
    col_v1, col_v2, col_v3 = st.columns(3)
    col_v1.metric("DIST TO FIELD", f"{round(top_apt['distance'], 1)} NM")
    col_v2.metric("MIN TARGET ALT", f"{int(alt_needed_for_straight_in)} FT")
    
    if excess_energy > 3000:
        col_v3.metric("ENERGY STATE", "HIGH", delta=f"+{int(excess_energy)} FT", delta_color="inverse")
        st.warning("⚠️ HIGH ENERGY: Track to High Key (3000' AGL over field). Execute 360° S-Turns to burn altitude.")
    elif excess_energy < 0:
        col_v3.metric("ENERGY STATE", "CRITICAL", delta=f"{int(excess_energy)} FT", delta_color="inverse")
        st.error("⚠️ LOW ENERGY: Glide compromised. Delay gear and flaps until runway is assured.")
    else:
        col_v3.metric("ENERGY STATE", "OPTIMAL", delta="ON GLIDEPATH")
        st.success("✅ OPTIMAL ENERGY: Execute straight-in approach to High Key transition.")

    st.markdown("### 🌍 SITUATIONAL AWARENESS DISPLAY")
    view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=8, pitch=30)
    st.pydeck_chart(pdk.Deck(
        map_style='mapbox://styles/mapbox/dark-v10',
        layers=[
            pdk.Layer("ScatterplotLayer", data=[{"lat": float(top_apt['latitude_deg']), "lon": float(top_apt['longitude_deg'])}], get_position="[lon, lat]", get_color="[0, 255, 0, 255]", get_radius=1500),
            pdk.Layer("ScatterplotLayer", data=[{"lat": lat, "lon": lon}], get_position="[lon, lat]", get_color="[255, 255, 255, 255]", get_radius=800),
            pdk.Layer("LineLayer", data=[{"start": [lon, lat], "end": [float(top_apt['longitude_deg']), float(top_apt['latitude_deg'])]}], get_source_position="start", get_target_position="end", get_color="[0, 255, 0, 200]", get_width=5)
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
