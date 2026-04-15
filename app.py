import streamlit as st
import pandas as pd
import math

# --- 1. CONFIGURATION & DATA ---
st.set_page_config(page_title="AeroAid Global", layout="wide")

AIRCRAFT_DATA = {
    "Boeing 737-800": {"glide_ratio": 17, "min_runway": 6500, "v_glide": 210},
    "Boeing 777-300ER": {"glide_ratio": 19, "min_runway": 8000, "v_glide": 230},
    "Boeing 787-9": {"glide_ratio": 20, "min_runway": 8500, "v_glide": 220},
    "Airbus A320": {"glide_ratio": 17, "min_runway": 6000, "v_glide": 200},
}

AIRLINES = ["United Airlines", "Delta Air Lines", "Qatar Airways", "Spirit Airlines", "Air India", "Singapore Airlines", "Qantas"]

@st.cache_data
def load_global_data():
    # Loading live global database of ~70,000 airports
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    df = pd.read_csv(url)
    # Keeping only large/medium airports for "legit" commercial landing
    df = df[df['type'].isin(['large_airport', 'medium_airport'])].copy()
    # Clean up empty values to prevent math errors
    df = df.dropna(subset=['iso_country', 'municipality', 'name', 'latitude_deg', 'longitude_deg'])
    return df

all_airports = load_global_data()

# --- 2. MATH ENGINES ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 # Nautical Miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    phi2_rad = math.radians(lat2)
    dphi = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2_rad)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 3. UI: INPUTS & SEARCH ---
st.title("✈️ AeroAid: Global Emergency Copilot")
st.sidebar.error("⚠️ TRAINING USE ONLY")

with st.sidebar:
    st.header("1. Flight Identity")
    airline = st.selectbox("Airline", AIRLINES)
    ac_type = st.selectbox("Aircraft Type", list(AIRCRAFT_DATA.keys()))
    
    st.header("2. Search Location (Clue)")
    # User types a city, country, or airport name
    search_clue = st.text_input("Enter City or Airport Clue", "Changi")
    
    # Logic to find coordinates from the "clue"
    results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False) | 
        all_airports['municipality'].str.contains(search_clue, case=False) |
        all_airports['ident'].str.contains(search_clue, case=False)
    ].head(1)
    
    # Auto-fill Lat/Long based on search clue
    if not results.empty:
        found_lat = float(results.iloc['latitude_deg'])
        found_lon = float(results.iloc['longitude_deg'])
        st.success(f"Located near: {results.iloc['municipality']}")
    else:
        found_lat, found_lon = 0.0, 0.0
        st.info("No matching location clue found. Enter manual coordinates.")

    lat = st.number_input("Current Latitude", value=found_lat, format="%.4f")
    lon = st.number_input("Current Longitude", value=found_lon, format="%.4f")
    alt = st.number_input("Altitude (MSL ft)", value=35000, step=1000)

# --- 4. LOGIC: EMERGENCY ANALYSIS ---
if st.button("CALCULATE EMERGENCY TRAJECTORY", type="primary"):
    ac = AIRCRAFT_DATA[ac_type]
    
    # Calculate Distances to EVERY airport in the world
    current_airports = all_airports.copy()
    current_airports['distance'] = current_airports.apply(
        lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1
    )
    
    # Sort and pick top options
    ranked = current_airports.sort_values('distance').head(5)
    
    if not ranked.empty:
        # FIXED: Accessing the first row safely to avoid TypeError
        top_apt = ranked.iloc 
        
        # Physics: Glide Capability
        max_glide_nm = (alt / 6076) * ac['glide_ratio'] * 0.7 # 30% Safety Factor
        dist_to_field = top_apt['distance']
        
        # Display Recommendation
        st.subheader(f"Diverting {airline} Flight")
        
        if dist_to_field <= max_glide_nm:
            st.success(f"**AI Recommendation:** Divert to **{top_apt['name']} ({top_apt['ident']})**.")
            st.write(f"This airport is {round(dist_to_field, 1)}nm away and within your safe glide profile of {round(max_glide_nm, 1)}nm.")
        else:
            st.error(f"**CRITICAL WARNING:** **{top_apt['name']}** is the closest field, but is {round(dist_to_field - max_glide_nm, 1)}nm beyond your safe glide range.")

        # Trajectory Grid
        cols = st.columns(3)
        for i in range(min(3, len(ranked))):
            apt = ranked.iloc[i]
            with cols[i]:
                st.markdown(f"### {apt['ident']}")
                st.metric("Distance", f"{round(apt['distance'], 1)} NM")
                st.caption(f"{apt['name']}, {apt['iso_country']}")
                if apt['distance'] <= max_glide_nm:
                    st.write("🟢 REACHABLE")
                else:
                    st.write("🔴 UNREACHABLE")

        # Visualizing the Trajectory
        st.divider()
        st.subheader("Trajectory Data")
        st.write(f"**Aircraft:** {ac_type} | **Glide Ratio:** {ac['glide_ratio']}:1")
        st.write(f"**Recommended Profile:** Descent at {ac['v_glide']} KIAS. Aim for 3.5° glideslope.")
