import streamlit as st
import pandas as pd
import math
import numpy as np

# --- 1. CONFIGURATION & DATA ---
st.set_page_config(page_title="AeroAid Pro: Emergency Copilot", layout="wide")

AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide": 210},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide": 230},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide": 220},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide": 200},
}

AIRLINES = ["United Airlines", "Delta Air Lines", "Qatar Airways", "Spirit Airlines", "Air India", "Singapore Airlines", "Qantas"]

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
    # Filter for Hard Surfaces (Asphalt, Concrete, Macadam)
    hard_surfaces = ['ASP', 'CON', 'ASPH', 'CONC', 'MAC', 'PEM']
    df = df[df['surface'].astype(str).str.upper().isin(hard_surfaces)]
    return df

all_airports = load_airports()
all_runways = load_runways()

# --- 2. ADVANCED MATH & API ENGINES ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 # Nautical Miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_live_wind_component(heading_to_apt):
    # PLACEHOLDER FOR AVWX/CHECKWX API
    # Simulating a random wind scenario: e.g., 30 knots tailwind or headwind
    simulated_wind_dir = 270 # Wind from the West
    simulated_wind_spd = 40  # Knots
    
    # Calculate headwind/tailwind component
    angle_diff = math.radians(simulated_wind_dir - heading_to_apt)
    wind_component = simulated_wind_spd * math.cos(angle_diff)
    return wind_component # Positive = Tailwind, Negative = Headwind

def check_terrain_clearance(lat1, lon1, lat2, lon2, capture_altitude):
    # PLACEHOLDER FOR DEM API (e.g., OpenTopoData)
    # Simulating a terrain check. Let's pretend 1 in 10 routes has a mountain.
    conflict = np.random.choice([True, False], p=[0.1, 0.9])
    if conflict and capture_altitude < 10000:
        return False # Terrain conflict found
    return True # Clear path

def generate_trajectory(lat1, lon1, lat2, lon2, start_alt, target_alt, steps=5):
    # Generates a 3D trajectory plan for the Glideslope Envelope
    trajectory = []
    alt_step = (start_alt - target_alt) / steps
    for i in range(steps + 1):
        fraction = i / steps
        point_lat = lat1 + (lat2 - lat1) * fraction
        point_lon = lon1 + (lon2 - lon1) * fraction
        point_alt = start_alt - (alt_step * i)
        trajectory.append({"Waypoint": i, "Lat": round(point_lat, 4), "Lon": round(point_lon, 4), "Target Alt (ft)": int(point_alt)})
    return pd.DataFrame(trajectory)

# --- 3. UI: INPUTS & SEARCH ---
st.title("✈️ AeroAid Pro: Global Emergency Copilot")
st.sidebar.error("⚠️ TRAINING USE ONLY")

with st.sidebar:
    st.header("1. Flight Identity")
    airline = st.selectbox("Airline", AIRLINES)
    ac_type = st.selectbox("Aircraft Type", list(AIRCRAFT_DATA.keys()))
    
    st.header("2. Search Location (Clue)")
    search_clue = st.text_input("Enter City or Airport Clue", "Singapore")
    
    search_results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False, na=False) | 
        all_airports['municipality'].str.contains(search_clue, case=False, na=False) |
        all_airports['ident'].str.contains(search_clue, case=False, na=False)
    ]
    
    if not search_results.empty:
        first_row = search_results.iloc[0]
        found_lat = float(first_row['latitude_deg'])
        found_lon = float(first_row['longitude_deg'])
        st.success(f"📍 Found: {first_row['municipality']}")
    else:
        found_lat, found_lon = 0.0, 0.0
        st.warning("No location found. Type a clue above.")

    lat = st.number_input("Current Latitude", value=found_lat, format="%.4f")
    lon = st.number_input("Current Longitude", value=found_lon, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=35000, step=1000)

# --- 4. LOGIC: ANALYSIS ---
if st.button("DECLARE EMERGENCY & CALCULATE TRAJECTORY", type="primary"):
    ac = AIRCRAFT_DATA[ac_type]
    
    # 🚨 ACTION PROMPTS: IMMEDIATE MEMORY ITEMS
    st.error(f"🚨 {ac_type.upper()} IMMEDIATE ACTION ITEMS 🚨")
    cols_alert = st.columns(3)
    cols_alert[0].markdown("### 1. AIRSPEED\n**MAINTAIN V-GLIDE**")
    cols_alert[1].markdown("### 2. LANDING GEAR\n**UP**")
    cols_alert[2].markdown("### 3. FLAPS\n**UP**")
    st.markdown("---")
    
    # Filtering Runways for Aircraft Requirements
    valid_runways = all_runways[all_runways['length_ft'] >= ac['min_runway']]
    valid_airport_idents = valid_runways['airport_ident'].unique()
    
    calc_df = all_airports[all_airports['ident'].isin(valid_airport_idents)].copy()
    calc_df['distance'] = calc_df.apply(
        lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1
    )
    
    ranked = calc_df.sort_values('distance').head(3)
    
    if not ranked.empty:
        top_apt = ranked.iloc[0]
        dist_to_field = top_apt['distance']
        
        # Wind corrected max glide
        sim_heading = 180 # Placeholder heading
        wind_comp = get_live_wind_component(sim_heading)
        
        # Ground speed adjustment
        gs = ac['v_glide'] + wind_comp
        max_glide_nm = (alt / 6076) * ac['glide_ratio'] * (gs / ac['v_glide']) * 0.7
        
        st.subheader(f"3D Trajectory Analysis for {airline}")
        
        terrain_clear = check_terrain_clearance(lat, lon, top_apt['latitude_deg'], top_apt['longitude_deg'], top_apt.get('elevation_ft', 0) + 2000)
        
        if not terrain_clear:
            st.error(f"⛰️ **UNREACHABLE - TERRAIN CONFLICT:** High terrain detected on path to {top_apt['ident']}.")
        elif dist_to_field <= max_glide_nm:
            st.success(f"✅ **Safe Divert:** {top_apt['name']} ({top_apt['ident']})")
            st.info(f"💨 **Wind Profile:** Calculated Groundspeed: {int(gs)} knots ({int(wind_comp)} kt component)")
            
            # Glideslope Envelope (3:1 Rule & Trajectory)
            st.markdown("### 📉 Glideslope Envelope & Trajectory Plan")
            capture_alt = max(top_apt.get('elevation_ft', 0) + 3000, 3000) # 3000ft AGL capture
            traj_df = generate_trajectory(lat, lon, top_apt['latitude_deg'], top_apt['longitude_deg'], alt, capture_alt)
            st.table(traj_df)
            
        else:
            st.error(f"🚨 **Critical:** {top_apt['ident']} is {round(dist_to_field - max_glide_nm, 1)}nm beyond wind-corrected glide range.")

        # Show alternatives
        st.markdown("---")
        st.markdown("### Alternative Airfields (Surface/Length Verified)")
        cols = st.columns(3)
        for i in range(min(3, len(ranked))):
            apt = ranked.iloc[i]
            with cols[i]:
                st.markdown(f"**{apt['ident']}**")
                st.write(f"{round(apt['distance'], 1)} NM")
                st.caption(f"{apt['municipality']}")
                status = "🟢 Reachable" if apt['distance'] <= max_glide_nm else "🔴 Out of Range"
                st.write(status)
    else:
        st.error("No suitable hard-surface runways found in range.")
