import streamlit as st
import pandas as pd
import math
import numpy as np
import pydeck as pdk
import requests

# --- 1. CONFIGURATION & DATA ---
st.set_page_config(page_title="AeroAid Pro: Level D", layout="wide")

AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide_max": 210, "empty_wt": 90000, "max_fuel": 46000},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide_max": 230, "empty_wt": 370000, "max_fuel": 320000},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide_max": 220, "empty_wt": 284000, "max_fuel": 223000},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide_max": 200, "empty_wt": 94000, "max_fuel": 42000},
}

@st.cache_data
def load_airports():
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    df = pd.read_csv(url)
    df = df[df['type'].isin(['large_airport', 'medium_airport'])].copy()
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

# --- 2. ADVANCED MATH & APIs ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

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
        # Check Low End (LE)
        if not pd.isna(rwy['le_heading_degT']):
            diff = abs((wind_dir - rwy['le_heading_degT'] + 180) % 360 - 180)
            if diff < best_diff:
                best_diff = diff
                best_rwy = f"{rwy['le_ident']} (Hdg: {int(rwy['le_heading_degT'])}°)"
                
        # Check High End (HE)
        if not pd.isna(rwy['he_heading_degT']):
            diff = abs((wind_dir - rwy['he_heading_degT'] + 180) % 360 - 180)
            if diff < best_diff:
                best_diff = diff
                best_rwy = f"{rwy['he_ident']} (Hdg: {int(rwy['he_heading_degT'])}°)"
                
    return best_rwy

# --- 3. UI: INPUTS ---
st.title("✈️ AeroAid Pro: Level D")

with st.sidebar:
    st.header("1. Flight Profile")
    ac_type = st.selectbox("Aircraft", list(AIRCRAFT_DATA.keys()))
    fuel_pct = st.slider("Current Fuel %", 0, 100, 50)
    
    st.header("2. Position")
    lat = st.number_input("Latitude", value=1.3644, format="%.4f")
    lon = st.number_input("Longitude", value=103.9915, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=35000, step=1000)

    use_live_wx = st.checkbox("Fetch Live METAR Weather", value=False)
    if not use_live_wx:
        st.header("3. Environment (Simulated)")
        sim_wind_dir = st.slider("Wind Direction (True)", 1, 360, 270)
        sim_wind_spd = st.slider("Wind Speed (Knots)", 0, 100, 40)

# --- 4. AVIATE (CHECKLIST) ---
st.error("🚨 ENGINE FAILURE DETECTED: MEMORY ITEMS 🚨")
col1, col2, col3 = st.columns(3)
check_speed = col1.checkbox("1. AIRSPEED - SET V-GLIDE")
check_gear = col2.checkbox("2. LANDING GEAR - UP")
check_flaps = col3.checkbox("3. FLAPS - UP")

if not (check_speed and check_gear and check_flaps):
    st.warning("⚠️ COMPLETE MEMORY ITEMS TO UNLOCK FMS.")
    st.stop()

# --- 5. NAVIGATE & ANALYZE ---
st.success("✅ Aviate Complete. FMS Active.")

effective_alt = max(alt - 1500, 0)
ac = AIRCRAFT_DATA[ac_type]
current_wt = ac['empty_wt'] + (ac['max_fuel'] * (fuel_pct / 100))
max_wt = ac['empty_wt'] + ac['max_fuel']
v_glide = ac['v_glide_max'] * math.sqrt(current_wt / max_wt)

# --- THE BRUTALLY HONEST TWEAK: MLW WARNING ---
mlw_limit = ac['empty_wt'] * 1.4 
if current_wt > mlw_limit:
    st.warning(f"⚠️ OVERWEIGHT LANDING: Current weight {int(current_wt):,} lbs exceeds estimated MLW ({int(mlw_limit):,} lbs). Structural damage likely.")

# Filter airports
calc_df = all_airports.copy()
calc_df['distance'] = calc_df.apply(lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1)
ranked = calc_df.sort_values('distance').head(1)

if ranked.empty:
    st.error("No suitable airports found.")
    st.stop()

top_apt = ranked.iloc[0]

# --- METAR INTEGRATION ---
wind_dir, wind_spd = 0, 0
if use_live_wx:
    wx_data = get_live_metar(top_apt['ident'])
    if wx_data:
        wind_dir, wind_spd = wx_data['wdir'], wx_data['wspd']
        st.info(f"📡 **Live METAR for {top_apt['ident']}:** Wind {wind_dir:03d}@{wind_spd} kts")
    else:
        st.warning("📡 Live weather unavailable. Using calm winds.")
else:
    wind_dir, wind_spd = sim_wind_dir, sim_wind_spd

# --- RUNWAY PICKER ---
apt_runways = all_runways[all_runways['airport_ident'] == top_apt['ident']]
apt_runways = apt_runways[apt_runways['length_ft'] >= ac['min_runway']]

if apt_runways.empty:
    st.error(f"Airfield {top_apt['ident']} lacks a sufficient runway for {ac_type}.")
    st.stop()

best_rwy_str = select_best_runway(apt_runways, wind_dir)

# --- ENERGY MANAGEMENT VNAV ---
st.subheader(f"Target Acquired: {top_apt['ident']} | Assigned Runway: {best_rwy_str}")

field_elevation = top_apt.get('elevation_ft', 0)
if pd.isna(field_elevation): field_elevation = 0
high_key_alt = field_elevation + 3000

# Glide Gradient in feet per nautical mile
glide_gradient = 6076 / (ac['glide_ratio'] * 0.7) 

# VNAV Math
excess_alt = effective_alt - (top_apt['distance'] * glide_gradient) - high_key_alt

col_vnav1, col_vnav2 = st.columns(2)
col_vnav1.metric("Distance to Target", f"{round(top_apt['distance'], 1)} NM")

if excess_alt > 1000:
    col_vnav2.metric("VNAV Energy Status", f"+{int(excess_alt)} ft (HIGH)", delta_color="inverse")
    st.error("🚨 HIGH ENERGY STATE: Execute 360° S-Turns or Forward Slips to lose altitude before High Key.")
elif excess_alt < -1000:
    col_vnav2.metric("VNAV Energy Status", f"{int(excess_alt)} ft (LOW)", delta_color="inverse")
    st.error("🚨 LOW ENERGY STATE: Sink Rate Critical. Divert compromised.")
else:
    col_vnav2.metric("VNAV Energy Status", f"ON GLIDEPATH", delta="Optimal")
    st.success("🟢 Energy nominal. Proceed to High Key.")

# Map
view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=8)
ac_layer = pdk.Layer("ScatterplotLayer", data=[{"lat": lat, "lon": lon}], get_position="[lon, lat]", get_color="[255, 0, 0, 200]", get_radius=1500)
apt_layer = pdk.Layer("ScatterplotLayer", data=[{"lat": float(top_apt['latitude_deg']), "lon": float(top_apt['longitude_deg'])}], get_position="[lon, lat]", get_color="[0, 255, 0, 200]", get_radius=1500)
st.pydeck_chart(pdk.Deck(layers=[ac_layer, apt_layer], initial_view_state=view_state))
