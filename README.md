# GRIDLOCK — Parking-Induced Congestion Intelligence

AI-driven detection of illegal-parking hotspots in Bengaluru and their impact on traffic flow,
built for the Flipkart Gridlock Hackathon 2.0 — Prototype Phase (Theme 1: Poor Visibility on
Parking-Induced Congestion).

## What this is

A Streamlit dashboard built on 298,000+ real Bengaluru Traffic Police parking-violation records
(Nov 2023–Apr 2024). It identifies where illegal parking is concentrated, quantifies how that
parking is amplifying already-congested corridors, generates optimized patrol routes for
enforcement, and flags repeat-offender vehicles.

## Features

1. **Hotspot Map** — geo-clustered violation hotspots across Bengaluru with a weighted risk
   score (violations near schools/hospitals/crossings weighted higher than routine parking),
   plus time-of-day and day-of-week breakdowns.
2. **Traffic Flow Impact Quantification** — spatially joins these parking hotspots with Round 1's
   geohash-based traffic demand predictions, so a junction isn't just "high violations" — it's
   "high violations inside an already high-demand corridor," which is the actual enforcement
   priority signal.
3. **Smart Patrol Route Optimizer** — given a number of patrol units and a shift length, builds
   routes that prioritize high-risk hotspots reachable in the time available.
4. **Repeat Offenders** — flags vehicles crossing a violation-count threshold for escalated
   enforcement.

## Project structure

```
gridlock/
├── app.py                  # Main Streamlit app
├── data_utils.py            # Data loading, hotspot clustering, Round 1 geohash join
├── patrol_optimizer.py      # Patrol route optimization logic
├── requirements.txt
├── .streamlit/config.toml   # Theme
└── data/
    ├── violations.csv.gz          # Cleaned Round 2 dataset (included)
    └── round1_demand.csv          # OPTIONAL: Round 1 geohash demand data
```

## How to run locally

1. Install Python 3.10+ if you don't have it.
2. Open a terminal in this folder and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

3. It will open automatically at `http://localhost:8501`. If not, open that link manually.

That's it — no API keys, no database, no extra setup. The dataset is bundled in `data/`.

### Optional: enabling the Round 1 cross-dataset feature

If you have the Round 1 geohash traffic-demand file, drop it into `data/round1_demand.csv`
with at least these two columns (names are auto-detected, case-insensitive):
- a geohash column (e.g. `geohash`)
- a demand column (e.g. `demand` or `predicted_demand`)

Reload the app and the **Traffic Flow Impact Quantification** tab will activate automatically.
Without this file, that tab still works but shows violation density only.

## Deploying (what we used for the live demo)

Deployed on **Streamlit Community Cloud** (free):
1. Push this folder to a public GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. Click "New app", select the repo, branch `main`, main file path `app.py`.
4. Click Deploy. Takes about 2–3 minutes the first time.

## Data note

All vehicle numbers, IDs, and device codes in the dataset are anonymized/synthetic placeholders
(e.g. `FKN00GL4424`) as provided by HackerEarth for this challenge — no real personal data is used.
