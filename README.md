# multi-controller-sdn-load-balancing
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
1. **Topology setup:** Mininet runs OVS switches and attaches them to remote Ryu controllers (OpenFlow 1.3). Two scenarios are used: 5 switches (2 controllers) and 9 switches (3 controllers). :contentReference[oaicite:10]{index=10}  
2. **Monitoring & scoring:** Each controller periodically samples its own CPU %, memory %, and packet-in delta; these are combined with tunable weights into a normalized composite score. :contentReference[oaicite:11]{index=11}  
3. **Decision & migration:** When the score difference exceeds thresholds, the LB controller selects switch(es) to migrate (lightest or heaviest policy), installs fail-safe flows, and reassigns the switch with `ovs-vsctl set-controller`. Cooldown timers prevent oscillations. :contentReference[oaicite:12]{index=12}  
4. **Evaluation:** CSV logs are analyzed to produce time-series charts and fairness metrics (STD, DIFF, CV) and percentage improvements comparing NoLB vs LB. Typical outputs: KPI tables and annotated bar charts. :contentReference[oaicite:13]{index=13}

---

## Key results (summary)
- Enabling load balancing substantially improved fairness across controllers (large STD/CV reductions across tested weight groups). See `results/` for time-series and bar charts. Example improvements reported: CPU STD improvements up to ~99% (weight dependent) in some configurations. 

---

## Quickstart (run the experiments locally)
> **Prereqs:** Python 3.8+, Ryu, Mininet, Open vSwitch, psutil, pandas, matplotlib, Flask, ovs-libs. Run on a Linux VM with mininet installed.
