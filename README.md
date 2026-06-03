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
- Enabling load balancing substantially improved fairness across controllers (large STD/CV reductions across tested weight groups). 

---


<img width="667" height="391" alt="Topology 2" src="https://github.com/user-attachments/assets/335d122d-ff3d-4541-8002-a5d79fd93b38" />
<img width="673" height="301" alt="Topology 1" src="https://github.com/user-attachments/assets/44633229-6c83-4ef3-945a-9fd7ce277993" />







