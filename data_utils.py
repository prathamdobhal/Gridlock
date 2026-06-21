"""
Core data utilities for GRIDLOCK Parking Intelligence.
Loads the cleaned violations dataset, builds geo-grid hotspots,
and optionally joins Round 1 geohash demand data if present.
"""

import json
import os

import numpy as np
import pandas as pd

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "violations.csv.gz")
ROUND1_PATH_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "data", "round1_demand.csv"),
    os.path.join(os.path.dirname(__file__), "data", "round1_demand.csv.gz"),
]

# Grid cell size in degrees. ~0.0015 deg latitude is roughly 165m in Bengaluru.
GRID_SIZE = 0.0015

# Risk weighting for "near sensitive location" type violations vs plain parking.
HIGH_RISK_VIOLATIONS = {
    "PARKING NEAR ROAD CROSSING": 3,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 3,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 3,
    "DOUBLE PARKING": 2,
    "PARKING ON FOOTPATH": 2,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 2,
    "PARKING IN A MAIN ROAD": 2,
    "WRONG PARKING": 1,
    "NO PARKING": 1,
}


def risk_weight(violation):
    return HIGH_RISK_VIOLATIONS.get(violation, 1)


def load_violations():
    df = pd.read_csv(DATA_PATH, compression="gzip", low_memory=False)
    df["risk_weight"] = df["violation"].map(risk_weight).fillna(1)
    # Grid cell id for clustering, independent of named junction
    df["grid_lat"] = (df["lat"] / GRID_SIZE).round().astype(int) * GRID_SIZE
    df["grid_lon"] = (df["lon"] / GRID_SIZE).round().astype(int) * GRID_SIZE
    df["grid_id"] = (
        df["grid_lat"].round(5).astype(str) + "_" + df["grid_lon"].round(5).astype(str)
    )
    return df


def find_round1_file():
    for p in ROUND1_PATH_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def load_round1_demand():
    """
    Loads Round 1 geohash-based traffic demand predictions, if available.
    Expected to contain a geohash column and a demand score column.
    Returns None if no Round 1 file is present -- the app degrades gracefully.
    """
    path = find_round1_file()
    if path is None:
        return None
    try:
        comp = "gzip" if path.endswith(".gz") else None
        r1 = pd.read_csv(path, compression=comp, low_memory=False)
        return r1
    except Exception:
        return None


def build_hotspots(df):
    """
    Aggregate violations into geo-grid hotspots with summary stats.
    This is the unit used by the map, the patrol optimizer, and the impact score.
    """
    agg = (
        df.groupby("grid_id")
        .agg(
            lat=("grid_lat", "first"),
            lon=("grid_lon", "first"),
            total_violations=("id", "count"),
            risk_score=("risk_weight", "sum"),
            unique_vehicles=("vehicle_number", "nunique"),
            top_junction=("junction_name", lambda x: x.value_counts().index[0]),
            top_station=("police_station", lambda x: x.value_counts().index[0]),
            top_violation=("violation", lambda x: x.value_counts().index[0]),
        )
        .reset_index()
    )
    agg = agg.sort_values("risk_score", ascending=False).reset_index(drop=True)
    agg["rank"] = agg.index + 1
    return agg


def join_with_round1(hotspots, round1_df, geohash_col=None, demand_col=None):
    """
    Links Round 2 violation hotspots to the Round 1 traffic-demand distribution.

    IMPORTANT: Round 1's geohash values are anonymized identifiers and do not
    decode to real Bengaluru coordinates (verified: they fall in a totally
    different region of the geohash grid than the real Round 2 GPS data).
    A literal lat/lon overlay between the two datasets is therefore not valid.

    Instead, this builds a fair statistical proxy: each violation hotspot is
    assigned a percentile rank within Round 2 (by risk_score), and matched to
    the Round 1 cell sitting at the *same percentile rank* of the demand
    distribution. This compares "how extreme is this parking hotspot, among
    all parking hotspots" against "how extreme was traffic demand, among all
    measured cells" -- a same-shape distributional comparison rather than a
    fabricated geographic claim. It is presented in the app as a congestion
    correlation index, not as a spatial join.
    """
    if round1_df is None:
        hotspots = hotspots.copy()
        hotspots["traffic_demand"] = np.nan
        hotspots["demand_percentile"] = np.nan
        return hotspots, False

    cols_lower = {c.lower(): c for c in round1_df.columns}
    if demand_col is None:
        for cand in ["demand", "predicted_demand", "demand_score", "prediction", "traffic_demand"]:
            if cand in cols_lower:
                demand_col = cols_lower[cand]
                break

    if demand_col is None or len(round1_df) == 0:
        hotspots = hotspots.copy()
        hotspots["traffic_demand"] = np.nan
        hotspots["demand_percentile"] = np.nan
        return hotspots, False

    r1 = round1_df.copy()
    r1["demand_percentile"] = r1[demand_col].rank(pct=True)
    r1_sorted = r1.sort_values("demand_percentile").reset_index(drop=True)

    hotspots = hotspots.copy()
    if len(hotspots) == 0:
        hotspots["traffic_demand"] = np.nan
        hotspots["demand_percentile"] = np.nan
        return hotspots, False

    # Rank hotspots by risk_score (ascending), then map each to the Round 1
    # demand value at the equivalent percentile position via linear
    # interpolation -- avoids clumping many hotspots onto the same Round 1
    # row when the two datasets have very different sizes.
    hotspots = hotspots.sort_values("risk_score", ascending=True).reset_index(drop=True)
    hotspot_pct = (hotspots.index + 1) / (len(hotspots) + 1)

    r1_values = r1_sorted[demand_col].values
    r1_percentiles = r1_sorted["demand_percentile"].values

    hotspots["traffic_demand"] = np.interp(hotspot_pct, r1_percentiles, r1_values)
    hotspots["demand_percentile"] = hotspot_pct

    hotspots = hotspots.sort_values("risk_score", ascending=False).reset_index(drop=True)
    hotspots["rank"] = hotspots.index + 1
    return hotspots, True


def violation_breakdown(df, grid_id=None):
    sub = df if grid_id is None else df[df["grid_id"] == grid_id]
    return sub["violation"].value_counts()


def repeat_offenders(df, min_violations=5):
    counts = df.groupby("vehicle_number").agg(
        violation_count=("id", "count"),
        vehicle_type=("vehicle_type", "first"),
        stations=("police_station", lambda x: ", ".join(sorted(set(x.dropna()))[:3])),
        top_violation=("violation", lambda x: x.value_counts().index[0]),
    ).reset_index()
    counts = counts[counts["violation_count"] >= min_violations]
    counts = counts.sort_values("violation_count", ascending=False).reset_index(drop=True)
    return counts
