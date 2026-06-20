"""
Smart Patrol Route Optimizer.

Given a starting point, a number of available patrol units, and a shift duration,
this picks the highest-risk hotspots and sequences them into routes using a
nearest-neighbour heuristic -- a standard, explainable approach for this kind
of multi-stop routing (a lightweight stand-in for the vehicle routing problem).
"""

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0
AVG_PATROL_SPEED_KMH = 22  # realistic average for urban Bengaluru traffic
MINUTES_PER_STOP = 12  # time to inspect / issue notices at a hotspot


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def nearest_neighbour_route(points, start_lat, start_lon, time_budget_min):
    """
    points: DataFrame with lat, lon, risk_score, top_junction, total_violations
    Greedily visits the nearest unvisited high-value point, stopping when the
    shift time budget runs out. Returns the ordered route and a stats dict.
    """
    remaining = points.copy().reset_index(drop=True)
    route = []
    cur_lat, cur_lon = start_lat, start_lon
    time_used = 0.0

    while len(remaining) > 0 and time_used < time_budget_min:
        dists = haversine_km(cur_lat, cur_lon, remaining["lat"].values, remaining["lon"].values)
        travel_min = (dists / AVG_PATROL_SPEED_KMH) * 60
        total_min = travel_min + MINUTES_PER_STOP

        # Score candidates by risk captured per minute spent -- this is what
        # makes the route "smart" rather than just nearest-first: it prefers
        # high-risk stops that are also reasonably close.
        value_density = remaining["risk_score"].values / np.maximum(total_min, 1)
        best_idx = int(np.argmax(value_density))

        candidate_time = time_used + total_min[best_idx]
        if candidate_time > time_budget_min and len(route) > 0:
            break

        row = remaining.iloc[best_idx]
        route.append(
            {
                "stop_number": len(route) + 1,
                "grid_id": row["grid_id"],
                "lat": row["lat"],
                "lon": row["lon"],
                "junction": row["top_junction"],
                "station": row["top_station"],
                "risk_score": row["risk_score"],
                "total_violations": row["total_violations"],
                "travel_km": round(dists[best_idx], 2),
                "travel_min": round(travel_min[best_idx], 1),
            }
        )
        time_used += total_min[best_idx]
        cur_lat, cur_lon = row["lat"], row["lon"]
        remaining = remaining.drop(remaining.index[best_idx]).reset_index(drop=True)

    route_df = pd.DataFrame(route)
    stats = {
        "stops": len(route_df),
        "total_time_min": round(time_used, 1),
        "total_risk_covered": int(route_df["risk_score"].sum()) if len(route_df) else 0,
        "total_violations_covered": int(route_df["total_violations"].sum()) if len(route_df) else 0,
    }
    return route_df, stats


def optimize_patrols(hotspots, num_units, shift_hours, start_lat, start_lon, top_n=60):
    """
    Splits the top-N highest risk hotspots across num_units patrol routes.
    Assignment: round-robin by descending risk so each unit gets a mix of
    high-value stops rather than one unit getting all the best ones.
    """
    pool = hotspots.head(top_n).reset_index(drop=True)
    time_budget = shift_hours * 60

    unit_pools = [[] for _ in range(num_units)]
    for i, row in pool.iterrows():
        unit_pools[i % num_units].append(row)

    routes = []
    all_stats = []
    for unit_idx in range(num_units):
        unit_points = pd.DataFrame(unit_pools[unit_idx]) if unit_pools[unit_idx] else pd.DataFrame(
            columns=pool.columns
        )
        if len(unit_points) == 0:
            routes.append(pd.DataFrame())
            all_stats.append({"stops": 0, "total_time_min": 0, "total_risk_covered": 0, "total_violations_covered": 0})
            continue
        route_df, stats = nearest_neighbour_route(unit_points, start_lat, start_lon, time_budget)
        route_df.insert(0, "unit", f"Unit {unit_idx + 1}")
        routes.append(route_df)
        all_stats.append(stats)

    combined = pd.concat(routes, ignore_index=True) if routes else pd.DataFrame()
    summary = {
        "total_stops": sum(s["stops"] for s in all_stats),
        "total_risk_covered": sum(s["total_risk_covered"] for s in all_stats),
        "total_violations_covered": sum(s["total_violations_covered"] for s in all_stats),
        "avg_time_used_min": round(np.mean([s["total_time_min"] for s in all_stats]), 1) if all_stats else 0,
    }
    return combined, all_stats, summary
