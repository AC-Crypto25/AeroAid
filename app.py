import streamlit as st
import pandas as pd
import math
import numpy as np
import pydeck as pdk
import requests

# --- 1. CONFIGURATION & CUSTOM CSS (GLASS COCKPIT) ---
st.set_page_config(page_title="AeroAid Pro: Level D EFB", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stApp {
        background-color: #0b0f19;
        color: #00ff00;
        font-family: 'Courier New', Courier, monospace;
    }
    .pfd-card {
        background-color: #161b22;
        border: 2px solid #00ff00;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 0 0 10px rgba(0, 255, 0, 0.2);
    }
    .pfd-warning {
        border-color: #ff9900;
        box-shadow: 0 0 15px rgba(255, 153, 0, 0.4);
        color: #ff9900;
    }
    .pfd-critical {
        border-color: #ff0000;
        box-shadow: 0 0 15px rgba(255, 0, 0, 0.6);
        color: #ff0000;
    }
    h1, h2, h3 {
        color: #00ff00;
    }
</style>
""", unsafe_allow_html=True)

AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide_max": 210, "empty_wt": 90000, "max_fuel": 46000},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide_max": 230, "empty_wt": 370000, "max_fuel": 320000},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide_max": 220, "empty_wt": 284000, "max_fuel": 223000},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide_max": 200, "empty_wt": 94000, "max_fuel": 42000},
}

# Massive Global Expansion of Airlines
AIRLINES = sorted([
    "Aer Lingus", "Aeromexico", "Air Canada", "Air China", "Air France", "Air India", 
    "Air New Zealand", "All Nippon Airways (ANA)", "American Airlines", "Asiana Airlines",
    "Avianca", "British Airways", "Cathay Pacific", "China Eastern Airlines", "China Southern Airlines",
    "Delta Air Lines", "EgyptAir", "El Al", "Emirates", "Ethiopian Airlines", "Etihad Airways",
    "EVA Air", "Finnair", "Hawaiian Airlines", "Iberia", "IndiGo", "Japan Airlines (JAL)",
    "KLM Royal Dutch Airlines", "Korean Air", "LATAM Airlines", "Lufthansa", "Qantas",
    "Qatar Airways", "Ryanair", "SAS Scandinavian Airlines", "Singapore Airlines", 
    "South African Airways", "Southwest Airlines", "Spirit Airlines", "TAP Air Portugal", 
    "Turkish Airlines", "United Airlines", "Virgin Atlantic", "Volaris"
])

@st.cache_data
def load_airports():
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    df = pd.read_csv(url)
    # UNLOCKED: Removed the size filter. We now only filter out 'closed' airports.
    # The runway logic will filter out the small/unpaved ones later.
    df = df[df['type'] != 'closed'].copy()
    df = df.dropna(subset=['iso_country', 'municipality', 'name', 'latitude_deg', 'longitude_deg', 'ident'])
    return df

@st.cache_data
def load_runways():
    url = "https://davidmegginson.github.io/ourairports-data/runways.csv"
    df = pd.read_csv(url)
    hard_surfaces = ['ASP', 'CON', 'ASPH', 'CONC', 'MAC', 'PEM']
    df = df[df['surface'].astype(str).str.upper().isin(hard_surfaces)]
    df['le_heading_degT'] = pd.to_numeric(df['le_heading_degT'], errors='coerce')
    df['he_heading_degT'] = pd.to_numeric(df['he_heading_degT'], errors='coerce')
    return df

all_airports = load_airports()
all_runways = load_runways()

# --- 2. ADVANCED MATH, APIs & GEOMETRY ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def generate_glide_ring(center_lat, center_lon, radius_nm, points=36):
    ring = []
    lat_deg_per_nm = 1 / 60.0
    lon_deg_per_nm = 1 / (60.0 * math.cos(math.radians(center_lat)))
    
    for i in range(points):
        angle = math.radians(float(i) / points * 360.0)
        d_lat = radius_nm * math.cos(angle) * lat_deg_per_nm
        d_lon = radius_nm * math.sin(angle) * lon_deg_per_nm
        ring.append([center_lon + d_lon, center_lat + d_lat])
    return [ring]

def get_live_metar(icao):
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=1"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data:
            return {"wdir": data[0].get("wdir", 0), "wspd": data[0].get("wspd", 0)}
    except:
        return None
    return None

def select_best_runway(runways_df, wind_dir):
    best_rwy = None
    best_diff = 360
    for _, rwy in runways_df.iterrows():
        if not pd.isna(rwy['le_heading_degT']):
            diff = abs((wind_dir - rwy['le_heading_degT'] + 180) % 360 - 180)
            if diff < best_diff:
                best_diff = diff
                best_rwy = f"{rwy['le_ident']} (Hdg: {int(rwy['le_heading_degT'])}°)"
        if not pd.isna(rwy['he_heading_degT']):
            diff = abs((wind_dir - rwy['he_heading_degT'] + 180) % 360 - 180)
            if diff < best_diff:
                best_diff = diff
                best_rwy = f"{rwy['he_ident']} (Hdg: {int(rwy['he_heading_degT'])}°)"
    return best_rwy

def calculate_time_to_impact(distance_nm, groundspeed_kts):
    if groundspeed_kts <= 0: return "N/A"
    time_hours = distance_nm / groundspeed_kts
    minutes = int(time_hours * 60)
    seconds = int((time_hours * 60 % 1) * 60)
    return f"{minutes:02d}:{seconds:02d}"

# --- 3. UI: INPUTS & SEARCH ---
st.title("✈️ AeroAid Pro: EFB Level D")

with st.sidebar:
    st.header("1. Flight Identity")
    airline = st.selectbox("Airline Operator", AIRLINES)
    ac_type = st.selectbox("Aircraft", list(AIRCRAFT_DATA.keys()))
    fuel_pct = st.slider("Current Fuel %", 0, 100, 50)
    
    st.header("2. Search Location (Clue)")
    search_clue = st.text_input("Enter City or Airport Clue", "London")
    
    search_results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False, na=False) | 
        all_airports['municipality'].str.contains(search_clue, case=False, na=False) |
        all_airports['ident'].str.contains(search_clue, case=False, na=False)
    ]
    
    if not search_results.empty:
        first_row = search_results.iloc[0]
        found_lat = float(first_row['latitude_deg'])
        found_lon = float(first_row['longitude_deg'])
        st.success(f"📍 GPS Lock: {first_row['municipality']} ({first_row['ident']})")
    else:
        found_lat, found_lon = 0.0, 0.0
        st.warning("NO DATA. Type clue above.")

    lat = st.number_input("Latitude", value=found_lat, format="%.4f")
    lon = st.number_input("Longitude", value=found_lon, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=35000, step=1000)

    use_live_wx = st.checkbox("Fetch Live METAR Weather", value=False)
    if not use_live_wx:
        st.header("3. Environment (Simulated)")
        sim_wind_dir = st.slider("Wind Direction (True)", 1, 360, 270)
        sim_wind_spd = st.slider("Wind Speed (Knots)", 0, 100, 40)

# --- 4. AVIATE (CHECKLIST) ---
st.error("🚨 MASTER CAUTION: ENGINE FAILURE DETECTED 🚨")
st.markdown("<div class='pfd-card pfd-critical'>", unsafe_allow_html=True)
st.write(f"**OPERATOR:** {airline.upper()} | **AIRFRAME:** {ac_type.upper()}")
col1, col2, col3 = st.columns(3)
check_speed = col1.checkbox("1. AIRSPEED - V-GLIDE")
check_gear = col2.checkbox("2. GEAR - UP")
check_flaps = col3.checkbox("3. FLAPS - UP")
st.markdown("</div>", unsafe_allow_html=True)

if not (check_speed and check_gear and check_flaps):
    st.warning("⚠️ EXECUTE MEMORY ITEMS TO UNLOCK FMS.")
    st.stop()

# --- 5. NAVIGATE & ANALYZE ---
effective_alt = max(alt - 1500, 0)
ac = AIRCRAFT_DATA[ac_type]
current_wt = ac['empty_wt'] + (ac['max_fuel'] * (fuel_pct / 100))
max_wt = ac['empty_wt'] + ac['max_fuel']
v_glide = ac['v_glide_max'] * math.sqrt(current_wt / max_wt)

max_glide_nm = (effective_alt / 6076) * ac['glide_ratio'] * 0.7

st.markdown("<div class='pfd-card'>", unsafe_allow_html=True)
st.write(f"**V-GLIDE:** {int(v_glide)} KTS | **REACTION ALT:** {effective_alt} FT | **MAX RANGE:** {round(max_glide_nm, 1)} NM")

mlw_limit = ac['empty_wt'] * 1.4 
if current_wt > mlw_limit:
    st.markdown(f"<span style='color:#ff0000;'><b>⚠️ OVERWEIGHT LANDING:</b> Weight ({int(current_wt):,} lbs) exceeds MLW. Expect structural damage.</span>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Filter global airports dynamically based strictly on aircraft runway requirements
valid_runways = all_runways[all_runways['length_ft'] >= ac['min_runway']]
valid_airport_idents = valid_runways['airport_ident'].unique()

calc_df = all_airports[all_airports['ident'].isin(valid_airport_idents)].copy()
calc_df['distance'] = calc_df.apply(lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1)
ranked = calc_df.sort_values('distance').head(1)

if ranked.empty:
    st.error("SYSTEM FAILURE: No suitable hard-surface runways found in the global database near your location.")
    st.stop()

top_apt = ranked.iloc[0]

# --- METAR INTEGRATION ---
wind_dir, wind_spd = 0, 0
if use_live_wx:
    wx_data = get_live_metar(top_apt['ident'])
    if wx_data:
        wind_dir, wind_spd = wx_data['wdir'], wx_data['wspd']
        st.info(f"📡 DATALINK: METAR {top_apt['ident']} Wind {wind_dir:03d}@{wind_spd}KT")
    else:
        st.warning("📡 DATALINK FAILED. Using calm winds.")
else:
    wind_dir, wind_spd = sim_wind_dir, sim_wind_spd

# --- RUNWAY PICKER & TIME TO FIELD ---
apt_runways = valid_runways[valid_runways['airport_ident'] == top_apt['ident']]
best_rwy_str = select_best_runway(apt_runways, wind_dir)

heading_to_apt = math.degrees(math.atan2(top_apt['longitude_deg'] - lon, top_apt['latitude_deg'] - lat)) % 360
wind_angle_diff = math.radians(wind_dir - heading_to_apt)
headwind_comp = wind_spd * math.cos(wind_angle_diff)
groundspeed = max(v_glide - headwind_comp, 50) 

tti_str = calculate_time_to_impact(top_apt['distance'], groundspeed)

# --- ENERGY MANAGEMENT VNAV ---
st.subheader(f"TARGET: {top_apt['name']} ({top_apt['ident']}) | RWY: {best_rwy_str}")

field_elevation = top_apt.get('elevation_ft', 0)
if pd.isna(field_elevation): field_elevation = 0
high_key_alt = field_elevation + 3000
glide_gradient = 6076 / (ac['glide_ratio'] * 0.7) 
excess_alt = effective_alt - (top_apt['distance'] * glide_gradient) - high_key_alt

st.markdown("<div class='pfd-card'>", unsafe_allow_html=True)
col_vnav1, col_vnav2, col_vnav3 = st.columns(3)
col_vnav1.metric("DIST TO TARGET", f"{round(top_apt['distance'], 1)} NM")
col_vnav2.metric("TIME TO IMPACT (TTI)", tti_str)

if excess_alt > 1000:
    col_vnav3.metric("VNAV ENERGY", f"+{int(excess_alt)} FT", delta_color="inverse")
    st.markdown("<span style='color:#ff9900;'><b>🚨 HIGH ENERGY:</b> Execute 360° S-Turns.</span>", unsafe_allow_html=True)
elif excess_alt < -1000:
    col_vnav3.metric("VNAV ENERGY", f"{int(excess_alt)} FT", delta_color="inverse")
    st.markdown("<span style='color:#ff0000;'><b>🚨 LOW ENERGY:</b> Divert compromised.</span>", unsafe_allow_html=True)
else:
    col_vnav3.metric("VNAV ENERGY", "ON GLIDEPATH", delta="Optimal")
st.markdown("</div>", unsafe_allow_html=True)

# --- MAP: GLIDE RING & TARGET ---
st.markdown("**SITUATIONAL AWARENESS DISPLAY (SAD)**")
glide_ring_coords = generate_glide_ring(lat, lon, max_glide_nm)

view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=8, pitch=30)

ring_layer = pdk.Layer(
    "PolygonLayer",
    data=[{"polygon": glide_ring_coords[0]}],
    get_polygon="polygon",
    get_fill_color="[0, 255, 0, 30]",
    get_line_color="[0, 255, 0, 200]",
    line_width_min_pixels=2,
    pickable=False,
)

ac_layer = pdk.Layer(
    "ScatterplotLayer",
    data=[{"lat": lat, "lon": lon}],
    get_position="[lon, lat]",
    get_color="[255, 255, 255, 255]",
    get_radius=800,
)

apt_layer = pdk.Layer(
    "ScatterplotLayer",
    data=[{"lat": float(top_apt['latitude_deg']), "lon": float(top_apt['longitude_deg'])}],
    get_position="[lon, lat]",
    get_color="[0, 255, 0, 200]",
    get_radius=1200,
)

st.pydeck_chart(pdk.Deck(
    map_style='mapbox://styles/mapbox/dark-v10',
    layers=[ring_layer, apt_layer, ac_layer], 
    initial_view_state=view_state
))
