import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go

from data_utils import (
    load_violations,
    build_hotspots,
    load_round1_demand,
    join_with_round1,
    violation_breakdown,
    repeat_offenders,
)
from patrol_optimizer import optimize_patrols

st.set_page_config(
    page_title="GRIDLOCK | Parking Intelligence",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #0B1929; }
    [data-testid="stMetricValue"] { font-size: 1.8rem; color: #F2B134; }
    [data-testid="stMetricLabel"] { color: #9FB3C8; }
    .gl-badge {
        display: inline-block; padding: 2px 10px; border-radius: 12px;
        font-size: 0.75rem; font-weight: 600; margin-right: 6px;
    }
    .gl-badge-high { background-color: #E63946; color: white; }
    .gl-badge-med { background-color: #F2B134; color: #0B1929; }
    .gl-badge-low { background-color: #06D6A0; color: #0B1929; }
    .gl-card {
        background-color: #142A42; border-radius: 10px; padding: 16px 20px;
        margin-bottom: 10px;
    }
    h1, h2, h3 { color: #E8EEF5; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data loading (cached so it only runs once per session)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading 298K+ violation records...")
def get_data():
    df = load_violations()
    hotspots = build_hotspots(df)
    round1 = load_round1_demand()
    hotspots, has_round1 = join_with_round1(hotspots, round1)
    return df, hotspots, has_round1


df, hotspots_all, has_round1 = get_data()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
st.sidebar.markdown("## 🚦 GRIDLOCK")
st.sidebar.caption("Parking-Induced Congestion Intelligence · Bengaluru")
st.sidebar.markdown("---")

stations = sorted(df["police_station"].dropna().unique().tolist())
vehicle_types = sorted(df["vehicle_type"].dropna().unique().tolist())
violations_list = sorted(df["violation"].dropna().unique().tolist())

sel_stations = st.sidebar.multiselect("Police Station", stations, default=[])
sel_vehicles = st.sidebar.multiselect("Vehicle Type", vehicle_types, default=[])
sel_violations = st.sidebar.multiselect("Violation Type", violations_list, default=[])

months = sorted(df["month"].dropna().unique().tolist())
sel_months = st.sidebar.select_slider(
    "Month range", options=months, value=(months[0], months[-1])
)

filtered = df.copy()
if sel_stations:
    filtered = filtered[filtered["police_station"].isin(sel_stations)]
if sel_vehicles:
    filtered = filtered[filtered["vehicle_type"].isin(sel_vehicles)]
if sel_violations:
    filtered = filtered[filtered["violation"].isin(sel_violations)]
filtered = filtered[(filtered["month"] >= sel_months[0]) & (filtered["month"] <= sel_months[1])]

st.sidebar.markdown("---")
st.sidebar.metric("Records in view", f"{len(filtered):,}")
if has_round1:
    st.sidebar.success("Round 1 traffic demand data linked ✓")
else:
    st.sidebar.info("Round 1 demand data not loaded — Impact Quantification tab will show violation-only view.")

# Recompute hotspots on filtered data so every tab respects the sidebar filters
hotspots = build_hotspots(filtered) if len(filtered) else hotspots_all.iloc[0:0]
if has_round1:
    round1_full = load_round1_demand()
    hotspots, _ = join_with_round1(hotspots, round1_full)

# ---------------------------------------------------------------------------
# Header + KPIs
# ---------------------------------------------------------------------------
st.title("🚦 GRIDLOCK — Parking-Induced Congestion Intelligence")
st.caption(
    "AI-driven detection of illegal-parking hotspots and their impact on Bengaluru traffic flow, "
    "built for targeted Bengaluru Traffic Police enforcement."
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Violations", f"{len(filtered):,}")
k2.metric("Active Hotspots", f"{len(hotspots):,}")
k3.metric("Police Stations Covered", f"{filtered['police_station'].nunique():,}")
k4.metric("Repeat Offender Vehicles", f"{(filtered.groupby('vehicle_number').size() >= 5).sum():,}")
top_viol = filtered["violation"].value_counts().idxmax() if len(filtered) else "—"
k5.metric("#1 Violation Type", top_viol[:18] + ("…" if len(top_viol) > 18 else ""))

st.markdown("---")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🗺️ Hotspot Map",
        "📊 Traffic Impact Quantification",
        "🚓 Smart Patrol Optimizer",
        "🔁 Repeat Offenders",
    ]
)

# ===========================================================================
# TAB 1: Hotspot Map
# ===========================================================================
with tab1:
    st.subheader("Where illegal parking is concentrated")
    st.caption(
        "Each point is a ~165m grid cell. Size and color reflect a weighted risk score "
        "(violations near schools, hospitals, crossings, and double-parking are weighted higher than routine parking)."
    )

    col_map, col_list = st.columns([2.2, 1])

    with col_map:
        if len(hotspots) == 0:
            st.warning("No data matches the current filters.")
        else:
            map_df = hotspots.head(500).copy()
            map_df = map_df.dropna(subset=["lat", "lon"])

            if len(map_df) == 0:
                st.warning("No valid hotspot coordinates found.")
                st.stop()
            max_risk = max(map_df["risk_score"].max(), 1)
            map_df["radius"] = 30 + (map_df["risk_score"] / max_risk) * 150
            map_df["color_r"] = 230
            map_df["color_g"] = (242 - (map_df["risk_score"] / max_risk) * 200).astype(int)
            map_df["color_b"] = 60

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position=["lon", "lat"],
                get_radius="radius",
                get_fill_color=["color_r", "color_g", "color_b", 160],
                pickable=True,
                stroked=True,
                get_line_color=[255, 255, 255, 60],
            )
            view_state = pdk.ViewState(
                latitude=float(map_df["lat"].mean()),
                longitude=float(map_df["lon"].mean()),
                zoom=10.3,
                pitch=30,
            )
            tooltip = {
                "html": "<b>{top_junction}</b><br/>Station: {top_station}<br/>"
                "Violations: {total_violations}<br/>Risk score: {risk_score}<br/>"
                "Top violation: {top_violation}",
                "style": {"backgroundColor": "#142A42", "color": "#E8EEF5"},
            }
            st.pydeck_chart(
                pdk.Deck(
                    layers=[layer],
                    initial_view_state=view_state,
                    tooltip=tooltip,
                    map_style="dark",
                )
            )

    with col_list:
        st.markdown("**Top 10 highest-risk hotspots**")
        if len(hotspots):
            top10 = hotspots.head(10)
            for _, row in top10.iterrows():
                badge = "gl-badge-high" if row["risk_score"] >= top10["risk_score"].quantile(0.66) else "gl-badge-med"
                st.markdown(
                    f"""<div class="gl-card">
                    <span class="gl-badge {badge}">RANK {int(row['rank'])}</span><br/>
                    <b>{row['top_junction']}</b><br/>
                    <small>{row['top_station']} · {int(row['total_violations'])} violations · risk {int(row['risk_score'])}</small>
                    </div>""",
                    unsafe_allow_html=True,
                )

    st.markdown("#### Violation type breakdown")
    vc = filtered["violation"].value_counts().head(10).reset_index()
    vc.columns = ["violation", "count"]
    fig = px.bar(
        vc, x="count", y="violation", orientation="h",
        color="count", color_continuous_scale=["#06D6A0", "#F2B134", "#E63946"],
    )
    fig.update_layout(
        plot_bgcolor="#0B1929", paper_bgcolor="#0B1929", font_color="#E8EEF5",
        yaxis=dict(autorange="reversed"), showlegend=False, coloraxis_showscale=False,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Violations by hour of day")
        hourly = filtered["hour"].value_counts().sort_index().reset_index()
        hourly.columns = ["hour", "count"]
        fig2 = px.area(hourly, x="hour", y="count")
        fig2.update_traces(line_color="#F2B134", fillcolor="rgba(242,177,52,0.25)")
        fig2.update_layout(
            plot_bgcolor="#0B1929", paper_bgcolor="#0B1929", font_color="#E8EEF5",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)
    with c2:
        st.markdown("#### Violations by day of week")
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        dow = filtered["dow"].value_counts().reindex(order).fillna(0).reset_index()
        dow.columns = ["day", "count"]
        fig3 = px.bar(dow, x="day", y="count")
        fig3.update_traces(marker_color="#E63946")
        fig3.update_layout(
            plot_bgcolor="#0B1929", paper_bgcolor="#0B1929", font_color="#E8EEF5",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig3, use_container_width=True)

# ===========================================================================
# TAB 2: Traffic Flow Impact Quantification (the differentiator)
# ===========================================================================
with tab2:
    st.subheader("Cross-Dataset Congestion Correlation Index")
    st.caption(
        "Most teams treat Round 1 and Round 2 as separate challenges. We use Round 1's "
        "traffic demand model to add a second, independent signal to every parking hotspot."
    )

    with st.expander("Methodology -- how this score is built (read before trusting the numbers)"):
        st.markdown(
            """
Round 1's `geohash` values are **anonymized identifiers** issued for that challenge --
they do not decode to real Bengaluru GPS coordinates (we verified this: decoding them
lands in the Indian Ocean, nowhere near Bengaluru). So a literal "overlay these two
datasets on one map" join would be fabricated, not real, and we won't present it as one.

What we do instead: we rank every Round 2 violation hotspot by its risk score, and every
Round 1 cell by its predicted demand, then match hotspots to demand values **at the same
percentile position** in each distribution. A hotspot in the top 5% of parking-violation
risk is paired with a Round 1 cell that was in the top 5% of traffic demand.

This is a **distributional correlation, not a spatial join** -- it tells BTP "this hotspot's
severity is comparable to the most demand-saturated zones Round 1 modeled," which is a
defensible, honest signal for prioritization, even without real coordinate overlap.
            """
        )

    if not has_round1:
        st.markdown("#### Violation density as a standalone view")
        proxy = hotspots.head(15)[["rank", "top_junction", "top_station", "total_violations", "risk_score"]]
        st.dataframe(proxy, use_container_width=True, hide_index=True)
    else:
        joined = hotspots.dropna(subset=["traffic_demand"]).copy()
        r1_count = len(load_round1_demand()) if load_round1_demand() is not None else 0
        st.success(
            f"Round 1 demand distribution linked -- {len(joined):,} hotspots scored "
            f"against {r1_count:,} Round 1 demand cells."
        )

        if len(joined):
            joined["risk_norm"] = (joined["risk_score"] - joined["risk_score"].min()) / (
                joined["risk_score"].max() - joined["risk_score"].min() + 1e-9
            )
            joined["impact_score"] = (
                0.5 * joined["demand_percentile"] + 0.5 * joined["risk_norm"]
            ) * 100
            joined = joined.sort_values("impact_score", ascending=False)

            st.markdown("#### Hotspots with the strongest combined severity signal")
            top_impact = joined.head(10)
            for _, row in top_impact.iterrows():
                st.markdown(
                    f"""<div class="gl-card">
                    <b>{row['top_junction']}</b> — Congestion correlation score {row['impact_score']:.0f}/100<br/>
                    <small>{int(row['total_violations'])} violations · matched Round 1 demand percentile: {row['demand_percentile']*100:.0f}th · {row['top_station']}</small>
                    </div>""",
                    unsafe_allow_html=True,
                )

            fig4 = px.scatter(
                joined, x="demand_percentile", y="total_violations", size="impact_score",
                color="impact_score", color_continuous_scale=["#06D6A0", "#F2B134", "#E63946"],
                hover_name="top_junction",
                labels={
                    "demand_percentile": "Matched Round 1 demand percentile",
                    "total_violations": "Violation Count",
                },
            )
            fig4.update_layout(
                plot_bgcolor="#0B1929", paper_bgcolor="#0B1929", font_color="#E8EEF5",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No hotspots could be scored against the Round 1 distribution.")

# ===========================================================================
# TAB 3: Smart Patrol Route Optimizer
# ===========================================================================
with tab3:
    st.subheader("Generate an optimal patrol route for available units")
    st.caption(
        "Given a number of patrol units and a shift length, this builds routes that "
        "prioritize high-risk hotspots reachable within the time budget — turning the "
        "hotspot list into something a station officer can actually act on."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        num_units = st.number_input("Patrol units available", min_value=1, max_value=10, value=3)
    with c2:
        shift_hours = st.slider("Shift duration (hours)", 1, 8, 4)
    with c3:
        station_choice = st.selectbox(
            "Start patrol from station", ["(Use busiest hotspot area)"] + stations
        )

    if st.button("🚓 Generate Optimized Routes", type="primary"):
        if len(hotspots) == 0:
            st.warning("No hotspots available under current filters.")
        else:
            if station_choice == "(Use busiest hotspot area)":
                start_lat = hotspots.iloc[0]["lat"]
                start_lon = hotspots.iloc[0]["lon"]
            else:
                station_rows = filtered[
                    filtered["police_station"] == station_choice
                ]

                if len(station_rows):
                    start_lat = float(station_rows["lat"].mean())
                    start_lon = float(station_rows["lon"].mean())
                else:
                    start_lat = float(hotspots.iloc[0]["lat"])
                    start_lon = float(hotspots.iloc[0]["lon"])

            with st.spinner("Optimizing routes..."):
                routes, stats_list, summary = optimize_patrols(
                    hotspots, num_units, shift_hours, start_lat, start_lon
                )

            s1, s2, s3 = st.columns(3)
            s1.metric("Total Stops Planned", summary["total_stops"])
            s2.metric("Risk Score Covered", summary["total_risk_covered"])
            s3.metric("Violations Addressed", summary["total_violations_covered"])

            st.markdown("#### Route map")
            routes = routes.dropna(subset=["lat", "lon"])
            if len(routes):
                colors = [[230, 57, 70], [242, 177, 52], [6, 214, 160], [29, 161, 242],
                          [155, 89, 182], [230, 126, 34], [52, 152, 219], [231, 76, 60],
                          [46, 204, 113], [241, 196, 15]]
                layers = []
                for i in range(num_units):
                    unit_route = routes[routes["unit"] == f"Unit {i+1}"]
                    if len(unit_route) == 0:
                        continue
                    path_coords = unit_route[["lon", "lat"]].values.tolist()
                    layers.append(
                        pdk.Layer(
                            "PathLayer",
                            data=[{"path": path_coords}],
                            get_path="path",
                            get_color=colors[i % len(colors)],
                            width_scale=10,
                            width_min_pixels=3,
                        )
                    )
                    layers.append(
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=unit_route,
                            get_position=["lon", "lat"],
                            get_radius=80,
                            get_fill_color=colors[i % len(colors)],
                            pickable=True,
                        )
                    )
                view_state = pdk.ViewState(
                    latitude=float(routes["lat"].mean()),
                    longitude=float(routes["lon"].mean()),
                    zoom=10.5,
                )
                st.pydeck_chart(
                    pdk.Deck(
                        layers=layers,
                        initial_view_state=view_state,
                        map_style="dark",
                        tooltip={"html": "<b>{junction}</b><br/>Stop #{stop_number}<br/>Risk: {risk_score}"},
                    )
                )

                st.markdown("#### Stop-by-stop schedule")
                for i in range(num_units):
                    unit_route = routes[routes["unit"] == f"Unit {i+1}"]
                    if len(unit_route) == 0:
                        continue
                    with st.expander(f"Unit {i+1} — {len(unit_route)} stops · {stats_list[i]['total_time_min']} min"):
                        st.dataframe(
                            unit_route[["stop_number", "junction", "station", "total_violations", "risk_score", "travel_km", "travel_min"]],
                            use_container_width=True, hide_index=True,
                        )
            else:
                st.warning("Could not build routes — try increasing shift duration or units.")
    else:
        st.info("Set your parameters above and click Generate to build patrol routes.")

# ===========================================================================
# TAB 4: Repeat Offenders
# ===========================================================================
with tab4:
    st.subheader("Vehicles with a pattern of repeated violations")
    st.caption(
        "Flags vehicles crossing a violation threshold so enforcement can escalate beyond "
        "a routine fine -- a practical use of data already collected."
    )

    min_viol = st.slider("Minimum violations to flag as repeat offender", 2, 20, 5)
    offenders = repeat_offenders(filtered, min_violations=min_viol)

    o1, o2 = st.columns(2)
    o1.metric("Repeat Offender Vehicles", f"{len(offenders):,}")
    max_count = (
        int(offenders["violation_count"].fillna(0).max())
        if len(offenders)
        else 0
    )

    o2.metric(
        "Most Violations (single vehicle)",
        max_count
    )
    if len(offenders):
        st.dataframe(
            offenders.rename(columns={
                "vehicle_number": "Vehicle Number",
                "violation_count": "Total Violations",
                "vehicle_type": "Type",
                "stations": "Stations Seen At",
                "top_violation": "Most Common Violation",
            }),
            use_container_width=True, hide_index=True, height=420,
        )

        fig5 = px.bar(offenders.head(15), x="violation_count", y="vehicle_number", orientation="h")
        fig5.update_traces(marker_color="#E63946")
        fig5.update_layout(
            plot_bgcolor="#0B1929", paper_bgcolor="#0B1929", font_color="#E8EEF5",
            yaxis=dict(autorange="reversed", title=""), xaxis_title="Violation count",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("No vehicles cross this threshold under current filters.")

st.markdown("---")
st.caption(
    "GRIDLOCK Hackathon 2.0 · Prototype Phase · Built on Bengaluru Traffic Police parking violation data (298K+ records, Nov 2023–Apr 2024)"
)
