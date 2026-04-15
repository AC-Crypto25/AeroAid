import streamlit as st
import math

# --- 1. DATA (Simplified for single-file Chromebook setup) ---
AIRCRAFT = {
    "Cessna 172": {"glide_ratio": 9, "min_runway": 1500},
    "Piper PA-28": {"glide_ratio": 10, "min_runway": 1600}
}

AIRPORTS = [
    {"code": "KPDK", "name": "DeKalb-Peachtree", "lat": 33.876, "lon": -84.302, "runway": 6001},
    {"code": "KRYY", "name": "Cobb County Intl", "lat": 34.013, "lon": -84.598, "runway": 6305},
    {"code": "KFTY", "name": "Fulton County", "lat": 33.779, "lon": -84.521, "runway": 5796},
    {"code": "KLZU", "name": "Gwinnett County", "lat": 33.978, "lon": -83.962, "runway": 6000},
    {"code": "KFFC", "name": "Falcon Field", "lat": 33.357, "lon": -84.572, "runway": 5101},
    {"code": "KGVL", "name": "Lee Gilmer Memorial", "lat": 34.272, "lon": -83.830, "runway": 5500}
]

EMERGENCIES = {
    "Engine Failure": {
        "immediate": ["Pitch for Best Glide (68 KIAS)", "Select Landing Site", "Fuel Selector BOTH"],
        "caution": "Do not attempt to turn back to the runway if below 1000ft AGL."
    },
    "Low Fuel": {
        "immediate": ["Enrich Mixture", "Check Fuel Gauges", "Land as soon as practical"],
        "caution": "Avoid steep banks to prevent fuel unporting."
    }
}

# --- 2. LOGIC ---
def get_distance(lat1, lon1, lat2, lon2):
    R = 3440.065 # Nautical Miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlow = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlow/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 2)

# --- 3. UI ---
st.set_page_config(page_title="AeroAid MVP", page_icon="✈️")

st.title("✈️ AeroAid")
st.caption("AI-Assisted Aviation Emergency Support (Training Only)")

st.sidebar.warning("⚠️ **TRAINING USE ONLY**\nNot for real flight operations.")

# Input Form
with st.expander("1. Enter Scenario Data", expanded=True):
    ac_type = st.selectbox("Aircraft", list(AIRCRAFT.keys()))
    em_type = st.selectbox("Emergency", list(EMERGENCIES.keys()))
    col1, col2 = st.columns(2)
    alt = col1.number_input("Altitude (ft MSL)", value=5000)
    curr_lat = col1.number_input("Latitude", value=34.00, format="%.4f")
    curr_lon = col2.number_input("Longitude", value=-84.30, format="%.4f")

# Calculations
max_range = (alt / 6076) * AIRCRAFT[ac_type]["glide_ratio"] * 0.7 # 0.7 is safety factor

if st.button("Analyze Options", type="primary"):
    st.subheader("2. Recommended Landing Sites")
    
    results = []
    for apt in AIRPORTS:
        dist = get_distance(curr_lat, curr_lon, apt['lat'], apt['lon'])
        reachable = dist <= max_range
        rwy_ok = apt['runway'] >= AIRCRAFT[ac_type]['min_runway']
        
        # Simple scoring
        score = 100 - (dist * 5)
        if not reachable: score -= 100
        if not rwy_ok: score -= 50
        
        results.append({**apt, "dist": dist, "reachable": reachable, "score": score})
    
    ranked = sorted(results, key=lambda x: x['score'], reverse=True)[:3]
    
    # AI Summary Simulation
    st.info(f"**AI Summary:** Based on your altitude of {alt}ft, **{ranked['code']}** is your best option. It is {ranked['dist']}nm away and within your safe glide profile.")
    
    c1, c2, c3 = st.columns(3)
    for i, apt in enumerate(ranked):
        with [c1, c2, c3][i]:
            st.metric(f"Rank {i+1}: {apt['code']}", f"{apt['dist']} NM")
            st.write("✅ Reachable" if apt['reachable'] else "❌ Unlikely")

    st.divider()
    st.subheader("3. Emergency Checklist")
    st.write(f"**{em_type} Procedures:**")
    for step in EMERGENCIES[em_type]['immediate']:
        st.write(f"- {step}")
    st.error(f"CAUTION: {EMERGENCIES[em_type]['caution']}")
