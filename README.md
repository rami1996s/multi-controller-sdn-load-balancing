# multi-controller-sdn-load-balancing

implemented with Hussein Mohammad in 2025

dynamic controller load-balancing for SDN (Ryu + Mininet) — dynamic switch migration, KPI analysis and visualization

**Short summary**  
This project implements and evaluates a dynamic controller load-balancing framework for multi-controller SDN environments. It uses Ryu controllers and Mininet topologies to compare No-Load-Balancing (NoLB) versus a migration-based Load-Balancing (LB) approach that moves switches between controllers when load imbalance is detected.

---

## Features
- Multi-controller experiments (2-controller and 3-controller topologies).
- Controller-side monitoring (CPU, memory, packet-in rate) and composite load score computation.
- Hybrid migration policy (lightest/heaviest switch selection, cooldown to avoid ping-pong).
- Post-processing analysis: time-series plots, KPI tables, fairness metrics (STD, DIFF, CV) and percent improvements.
- Animation generator to visualize switch migrations over time (GIF output).

---

---

## How it works (quick technical overview)
1. **Topology setup:** Mininet runs OVS switches and attaches them to remote Ryu controllers (OpenFlow 1.3). Two scenarios are used: 5 switches (2 controllers) and 9 switches (3 controllers).
2. **Monitoring & scoring:** Each controller periodically samples its own CPU %, memory %, and packet-in delta; these are combined with tunable weights into a normalized composite score. 
3. **Decision & migration:** When the score difference exceeds thresholds, the LB controller selects switch(es) to migrate (lightest or heaviest policy), installs fail-safe flows, and reassigns the switch with `ovs-vsctl set-controller`. Cooldown timers prevent oscillations. 
4. **Evaluation:** CSV logs are analyzed to produce time-series charts and fairness metrics (STD, DIFF, CV) and percentage improvements comparing NoLB vs LB. Typical outputs: KPI tables and annotated bar charts.

---

## Key results (summary)
- Enabling load balancing substantially improved fairness across controllers (large STD/CV reductions across tested weight groups). See `results/` for time-series and bar charts. Example improvements reported: CPU STD improvements up to ~99% (weight dependent) in some configurations. 

---

## Quickstart (run the experiments locally)
> **Prereqs:** Python 3.8+, Ryu, Mininet, Open vSwitch, psutil, pandas, matplotlib, Flask, ovs-libs. Run on a Linux VM with mininet installed.
> # in terminal 1: start controller C1 (NoLB)
ryu-manager controllers/controller_noLB.py

# in terminal 2: start controller C2 (NoLB) on different port
ryu-manager --ofp-tcp-listen-port 6634 controllers/controller_noLB.py

Launch Mininet topology (in another terminal):

sudo python3 topologies/topo_2ctrl.py
# this script will instantiate topology and assign switches to controllers
generate animation:

python3 analysis/generate_animation.py --logs results/migration_events.log --out results/animation.gif
Trigger traffic and collect logs:

# inside Mininet CLI:
pingall
# repeat pingall as described in the report

Run analysis:

python3 analysis/analyze_kpi.py --noLB logs/noLB_c1.csv logs/noLB_c2.csv --lb logs/lb_c1.csv logs/lb_c2.csv
# generates plots in results/

(For 3-controller scenario, use topo_3ctrl.py and analyze_kpi_3ctrl.py accordingly.)




