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
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    df = pd.read_csv(url)
    df = df[df['type'].isin(['large_airport', 'medium_airport'])].copy()
    df = df.dropna(subset=['iso_country', 'municipality', 'name', 'latitude_deg', 'longitude_deg'])
    return df

all_airports = load_global_data()

# --- 2. MATH ENGINE ---
def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065 # Nautical Miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2 if 'dlambda' in locals() else dlon/2)**2
    # Simplified haversine for stability
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 3. UI: INPUTS & SEARCH ---
st.title("✈️ AeroAid: Global Emergency Copilot")
st.sidebar.error("⚠️ TRAINING USE ONLY")

with st.sidebar:
    st.header("1. Flight Identity")
    airline = st.selectbox("Airline", AIRLINES)
    ac_type = st.selectbox("Aircraft Type", list(AIRCRAFT_DATA.keys()))
    
    st.header("2. Search Location (Clue)")
    search_clue = st.text_input("Enter City or Airport Clue", "Singapore")
    
    # SEARCH LOGIC: REWRITTEN TO BE BULLETPROOF
    search_results = all_airports[
        all_airports['name'].str.contains(search_clue, case=False) | 
        all_airports['municipality'].str.contains(search_clue, case=False) |
        all_airports['ident'].str.contains(search_clue, case=False)
    ]
    
    if not search_results.empty:
        # THE FIX: Use .iloc to get the row, THEN ['column'] to get the value.
        # This avoids the "Non-integer key" error entirely.
        first_row = search_results.iloc
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
if st.button("CALCULATE EMERGENCY TRAJECTORY", type="primary"):
    ac = AIRCRAFT_DATA[ac_type]
    
    # Global distance calculation
    calc_df = all_airports.copy()
    calc_df['distance'] = calc_df.apply(
        lambda row: haversine(lat, lon, row['latitude_deg'], row['longitude_deg']), axis=1
    )
    
    ranked = calc_df.sort_values('distance').head(5)
    
    if not ranked.empty:
        top_apt = ranked.iloc
        dist_to_field = top_apt['distance']
        max_glide_nm = (alt / 6076) * ac['glide_ratio'] * 0.7
        
        st.subheader(f"Analysis for {airline} | {ac_type}")
        
        if dist_to_field <= max_glide_nm:
            st.success(f"✅ **Safe Divert:** {top_apt['name']} ({top_apt['ident']})")
        else:
            st.error(f"🚨 **Critical:** {top_apt['ident']} is {round(dist_to_field - max_glide_nm, 1)}nm beyond glide range.")

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
        st.error("No airports found.")
