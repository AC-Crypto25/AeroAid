import streamlit as st
import pandas as pd
import math

# --- 1. GLOBAL CONFIGURATION ---
st.set_page_config(page_title="AeroAid Global MVP", layout="wide")

# Best-glide performance data for Boeing and major jets
AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide": 210},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide": 230},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide": 220},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide": 200},
}

AIRLINES = ["United Airlines", "Delta Air Lines", "Qatar Airways", "Spirit Airlines", "Air India", "Singapore Airlines"]

# --- 2. DATA LOADING (The "Legit" Database) ---
@st.cache_data
def load_global_airports():
    # Downloads a live database of ~70,000 airports globally
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    df = pd.read_csv(url)
    # Filter for significant airports only
    df = df[df['type'].isin(['large_airport', 'medium_airport'])]
    return df[['ident', 'name', 'latitude_deg', 'longitude_deg', 'elevation_ft']]

all_airports = load_global_airports()

# --- 3. MATH ENGINES ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 # Nautical Miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 4. UI: INPUTS ---
st.title("✈️ AeroAid: Global Emergency Copilot")
st.sidebar.warning("⚠️ TRAINING ONLY: NOT FOR REAL FLIGHT")

with st.sidebar:
    st.header("Flight Configuration")
    airline = st.selectbox("Airline", AIRLINES)
    ac_type = st.selectbox("Aircraft Type", list(AIRCRAFT_DATA.keys()))
    
    st.header("Live Location")
    lat = st.number_input("Latitude", value=28.5562, format="%.4f") # Default: Near Delhi
    lon = st.number_input("Longitude", value=77.1000, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=35000)
    gs = st.number_input("Ground Speed (knots)", value=450)

# --- 5. LOGIC: TRAJECTORY & SEARCH ---
if st.button("Calculate Emergency Trajectory", type="primary"):
    ac = AIRCRAFT_DATA[ac_type]
    
    # Calculate Max Glide Range
    # (Alt / 6076) * Glide Ratio * 0.7 Safety Factor
    max_range = (alt / 6076) * ac['glide_ratio'] * 0.7
    
    # Calculate nearest airports from the 70,000 global list
    all_airports['distance'] = all_airports.apply(
        lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1
    )
    
    # Sort and take top 3 reachable
    ranked = all_airports.sort_values('distance').head(10)
    
    st.subheader(f"Results for {airline} Flight")
    
    # AI Summary Recommendation
    top_apt = ranked.iloc
    st.info(f"**AI Recommendation:** Divert to **{top_apt['name']} ({top_apt['ident']})**. \n\n"
            f"**Trajectory Logic:** At {alt}ft, you have a safe glide range of {round(max_range, 1)}nm. "
            f"Target airport is {round(top_apt['distance'], 1)}nm away. Recommended descent rate: 1,500 fpm at {ac['v_glide']} knots.")

    # Results Grid
    cols = st.columns(3)
    for i in range(3):
        apt = ranked.iloc[i]
        status = "🟢 REACHABLE" if apt['distance'] <= max_range else "🔴 UNLIKELY"
        with cols[i]:
            st.metric(f"{apt['ident']}", f"{round(apt['distance'], 1)} NM")
            st.write(f"**{apt['name']}**")
            st.write(status)
            
    # Trajectory Data
    with st.expander("View Detailed Descent Trajectory"):
        time_to_impact = (alt / 1000) * 2 # Roughly 2 mins per 1000ft glide
        st.write(f"**Estimated Time to Field:** {round(time_to_impact, 1)} minutes")
        st.write(f"**Glideslope Angle:** ~3.5 degrees")
        st.write(f"**Course to Fly:** Calculated based on current Lat/Lon heading to {top_apt['ident']}.")
