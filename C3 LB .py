# controller3_LB.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, ether_types
from ryu.lib.packet import ether_types
from ryu.lib import hub
import psutil, os, requests
from threading import Thread
from flask import Flask, jsonify
import json
import time
from ryu.lib.packet import ipv4, icmp
import subprocess
import threading
import math
import csv

flask_app = Flask(__name__)
controller_instance = None

@flask_app.route('/load')
def report_load():
    with controller_instance.lock:
        total_delta = getattr(controller_instance, 'total_delta', 0)
        current_cpu = getattr(controller_instance, 'current_cpu', 0.0)
        current_mem = getattr(controller_instance, 'current_mem', 0.0)
        # cumulative packet_in count (like C1 and C2)
        total_pkt_in = sum(controller_instance.packet_counts.get(dpid, 0) for dpid in controller_instance.owned_switches)
    safe_delta = max(total_delta, 0)
    normalized_pkt_in = min(math.log1p(safe_delta) * 10, 100)
    score = round(controller_instance.a1 * current_cpu + controller_instance.a2 * current_mem + controller_instance.a3 * normalized_pkt_in, 2)
    return jsonify(cpu=current_cpu, mem=current_mem, pkt_in=total_pkt_in, score=score)
    
@flask_app.route('/switches')
def get_switches():
    return jsonify(sorted(controller_instance.owned_switches))

class C3LoadBalancingController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(C3LoadBalancingController, self).__init__(*args, **kwargs)
        global controller_instance
        controller_instance = self
        self.name = "C3" 
        self.datapaths = {}
        self.packet_counts = {}
        self.prev_packet_counts = {}
        self.owned_switches = set()
        self.lock = threading.Lock()
        self.current_cpu = 0.0
        self.current_mem = 0.0
        self.current_score = 0.0
        self.last_migration_time = {}
        # === Centralized score weights ===
        self.a1 = 0.1   # CPU weight
        self.a2 = 0.1   # Memory weight
        self.a3 = 0.8   # Packet_in weight
        # Peer URLs for C1 and C2
        self.peer_urls = {
            "c1": "http://127.0.0.1:8080/load",
            "c2": "http://127.0.0.1:8081/load"
        }
        self.mac_to_port = {}
        # Flow installation flag: set to False to disable during testing
        self.auto_install_flows = True
        Thread(target=lambda: flask_app.run(port=8082)).start()
        hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        dpid = ev.msg.datapath.id
        if dpid not in self.packet_counts:
            self.packet_counts[dpid] = 0
        self.packet_counts[dpid] += 1
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
          return
        if eth.ethertype not in (ether_types.ETH_TYPE_ARP, ether_types.ETH_TYPE_IP):
           return
        if eth.ethertype == ether_types.ETH_TYPE_IPV6:
           return
        # self.logger.info(f"[C3] Packet_in from dpid={dpid}, in_port={in_port}, ethertype={eth.ethertype}")
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
          # self.logger.info(f"[C3] Handling ARP")
          self._handle_arp(datapath, in_port, pkt)
          return
        elif eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt is None:
                # Not a valid IPv4 packet; ignore or handle differently if you want
                # self.logger.info(f"[C3] Invalid IPv4 packet, dropping")
                return
         
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst
            # self.logger.info(f"[C3] Handling IP packet from {src_ip} to {dst_ip}")

            # Learn source MAC to port mapping (L2 switch behavior)
            self.mac_to_port.setdefault(dpid, {})
            self.mac_to_port[dpid][eth.src] = in_port

            # Determine output port
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            out_port = self.mac_to_port[dpid].get(eth.dst, ofproto.OFPP_FLOOD)
            actions = [parser.OFPActionOutput(out_port)]

            # ICMP specific handling (optional)
            icmp_pkt = pkt.get_protocol(icmp.icmp)
            if icmp_pkt:
                # self.logger.info(f"[C3] ICMP packet detected from {src_ip} to {dst_ip}")
                # You can add ICMP-specific logic here if needed
                pass

            # Install flow if destination known (avoid flooding)
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_type=ether_types.ETH_TYPE_IP)
                self.add_flow(datapath, priority=1, match=match, actions=actions)
                # self.logger.info(f"Installed flow for {eth.src}  {eth.dst} on s{dpid}")

            # Send packet out
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=in_port,
                actions=actions,
                data=msg.data
            )
            datapath.send_msg(out) 
            # self.logger.info(f"[C3] Packet_out sent on port {out_port}")
            return 
        else:
            # self.logger.info(f"[C3] Unknown ethertype: {eth.ethertype}, dropping packet")
            return
                  
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        dpid_str = f"s{dpid}"

        self.logger.info("[C3] Register switch %s", dpid_str)

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Install default flow to send packets to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                  ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0,
                        match=match, instructions=inst)
        datapath.send_msg(mod)

        with self.lock:
            self.datapaths[dpid] = datapath
            self.packet_counts[dpid] = 0
            self.prev_packet_counts[dpid] = 0   # reset on rejoin
            self.owned_switches.add(dpid)
    
    def _handle_arp(self, datapath, in_port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        arp_pkt = pkt.get_protocol(arp.arp)

        # self.logger.info("[C3] Handling ARP request %s  %s", arp_pkt.src_ip, arp_pkt.dst_ip)

        # Flood the ARP request (let destination host reply)
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port,
            actions=actions,
            data=pkt.data
        )
        datapath.send_msg(out)

    def _monitor(self):
        # Ensure startup_time is set (fallback)
        if not hasattr(self, 'startup_time'):
            self.startup_time = time.time()
        if not hasattr(self, 'min_startup_delay'):
            self.min_startup_delay = 20
        if not hasattr(self, 'last_migration_time'):
            self.last_migration_time = {}   # track per-switch migration timestamps
            
        log_file = "/tmp/kpi_log_c3_LB.csv"

        # Create file with header if not exists
        if not os.path.exists(log_file):
            with open(log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "cpu", "memory", "packet_in_delta", "score"])
        time.sleep(5)
        self.prev_packet_counts = {}
        # Prime psutil to avoid first measurement being 0
        psutil.cpu_percent(interval=None)         # prime CPU counters
        process = psutil.Process(os.getpid())  # per-process memory
        while True:
            if not self.owned_switches:
                hub.sleep(2)
                continue

           
            deltas = {}
            total_delta = 0
            for dpid in self.owned_switches:
                current = self.packet_counts.get(dpid, 0)
                prev = self.prev_packet_counts.get(dpid, 0)
                delta = current - prev
                deltas[dpid] = delta
                total_delta += delta
                self.prev_packet_counts[dpid] = current
                
            with self.lock:
                self.total_delta = total_delta
                self.current_cpu = process.cpu_percent()     # process-level CPU %
                self.current_mem = process.memory_percent()  # process-level RAM %
            
            safe_delta = max(total_delta, 0)  
            normalized_pkt_in = min(math.log1p(safe_delta) * 10, 100)

            score = round(self.a1 * self.current_cpu + self.a2 * self.current_mem + self.a3 * normalized_pkt_in, 2)

            switch_list = [f"s{dpid}" for dpid in self.owned_switches]
            self.logger.info(f"[C3] CPU: {self.current_cpu:.1f}% | Memory: {self.current_mem:.1f}% | pkt_in: {total_delta} | Score: {score:.2f} | Switches: {switch_list}")

            for dpid in self.owned_switches:
                delta = deltas.get(dpid, 0)
                self.logger.info(f"[C3]  - s{dpid}: packet_in delta = {delta}")
                
            # Append to CSV
            with open(log_file, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([time.time(), self.current_cpu, self.current_mem, total_delta, score])
            
            # === Get peer metrics from both C1 and C2 ===
            peer_scores = {}
            for peer_name, peer_url in self.peer_urls.items():
                try:
                    resp = requests.get(peer_url, timeout=2)
                    peer_data = resp.json()
                    peer_scores[peer_name] = float(peer_data.get("score", 0))
                except Exception as e:
                    self.logger.error("[C3] Error contacting %s: %s", peer_name, e)
                    peer_scores[peer_name] = float('inf')  # Exclude failed peers from migration
               
            # === Warm-up check ===
            if not peer_scores or all(s == 0 for s in peer_scores.values()):
                self.logger.info("[C3] Peer scores not ready, skipping migration decision.")
                hub.sleep(10)
                continue
                
            # === Startup delay check ===
            uptime = time.time() - self.startup_time
            if uptime < self.min_startup_delay:
                self.logger.info("[C3] Still in startup period (%.1fs), skipping migration", uptime)
                hub.sleep(10)
                continue 
                              
            # Find least loaded peer for potential migration
            valid_peers = {k: v for k, v in peer_scores.items() if v != float('inf')}
            if not valid_peers:
                self.logger.error("[C3] No valid peers available")
                hub.sleep(10)
                continue
                
            min_peer = min(valid_peers.items(), key=lambda x: x[1])
            min_peer_name, min_peer_score = min_peer
            
            score_diff = abs(score - min_peer_score)
            self.logger.info("[C3] Score difference with %s: %.2f (Local: %.2f, Peer: %.2f)", 
                            min_peer_name, score_diff, score, min_peer_score)
            
            # === Hybrid Policy ===
            if score > min_peer_score and score_diff > 7 and len(self.owned_switches) > 1:
                if score_diff > 14:
                    # migrate heaviest
                    dpid = max(self.packet_counts.items(), key=lambda x: x[1] if x[0] in self.owned_switches else -1)[0]
                    self.logger.warning(f"[C3] Score diff > 14 → migrating HEAVIEST s{dpid} to {min_peer_name}")
                else:
                    # migrate lightest
                    dpid = min(self.packet_counts.items(), key=lambda x: x[1] if x[0] in self.owned_switches else 1e9)[0]
                    self.logger.warning(f"[C3] Score diff 7–14 → migrating LIGHTEST s{dpid} to {min_peer_name}")
                
                # Check per-switch cooldown
                now = time.time()
                last_time = self.last_migration_time.get(dpid, 0)
                if now - last_time < 8:
                    self.logger.info(f"[C3] Skipping migration of s{dpid} (cooldown active, migrated {now - last_time:.1f}s ago)")
                    hub.sleep(3)
                    continue
                    
                # Determine target port based on peer name
                target_ports = {"c1": 6633, "c2": 6634}
                target_port = target_ports.get(min_peer_name)
                
                if target_port:
                    success = self._migrate_switch(dpid, target_port)
                    if success:
                        self.last_migration_time[dpid] = time.time()   # record migration timestamp
                        self.owned_switches.discard(dpid)
                        self.logger.info(f"[C3] Successfully migrated s{dpid} to {min_peer_name}")
                        hub.sleep(3)
                    else:
                        self.logger.error(f"[C3] Migration of s{dpid} failed, keeping ownership")
                else:
                    self.logger.error(f"[C3] Unknown target peer: {min_peer_name}")
                    
            elif score > min_peer_score and score_diff > 7 and len(self.owned_switches) == 1:
                self.logger.info(f"[C3] Score difference {score_diff:.2f} observed , but only 1 switch → migration skipped")
                
            hub.sleep(3)

    def _migrate_switch(self, dpid, target_port):
        dpid_str = f"s{dpid}"
        datapath = self.datapaths.get(dpid)

        # 1. Install temporary fail-safe flow (NORMAL forwarding)
        if datapath:
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            match = parser.OFPMatch()  # match all packets
            actions = [parser.OFPActionOutput(ofproto.OFPP_NORMAL)]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=0,
                match=match,
                instructions=inst
            )
            datapath.send_msg(mod)
            self.logger.info("[C3] Installed temporary fail-safe flow on %s", dpid_str)

        # 2. Perform the migration
        cmd = f"ovs-vsctl set-controller {dpid_str} tcp:127.0.0.1:{target_port}"

        with self.lock:
            if dpid in self.datapaths:
                del self.datapaths[dpid]
            self.packet_counts.pop(dpid, None)
            self.prev_packet_counts.pop(dpid, None)  # reset counters
            self.owned_switches.discard(dpid)

        try:
            subprocess.run(cmd.split(), check=True)
            self.logger.info("[C3] Migrated %s to controller on port %d", dpid_str, target_port)

            from_ctrl = "c3"
            to_ctrl = "c1" if target_port == 6633 else "c2" if target_port == 6634 else "unknown"
            log_migration(dpid_str, from_ctrl, to_ctrl)
            return True   # explicit success
            
        except subprocess.CalledProcessError as e:
            self.logger.error("[C3] ovs-vsctl failed: %s\nOutput: %s", e, e.output if hasattr(e, 'output') else "N/A")
            return False  # explicit failure
        
    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                priority=priority, match=match,
                                instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

def log_migration(switch, from_ctrl, to_ctrl):
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("/tmp/migration_log.txt", "a") as f:
        f.write(f"{timestamp},{switch},{from_ctrl},{to_ctrl}\n")