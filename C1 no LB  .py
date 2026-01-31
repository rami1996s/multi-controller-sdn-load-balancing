# controller1_noLB.py (Modified for 3-controller architecture)
from ryu.base import app_manager
from ryu.lib import hub
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp
from ryu.lib.packet import ether_types
import psutil
import threading
import time
import subprocess
import requests
from flask import Flask, jsonify
from ryu.lib.packet import ipv4, icmp
from collections import defaultdict
import random
import math
import csv
import os

# Flask app to expose /load to C2 and C3
flask_app = Flask(__name__)

@flask_app.route('/load')
def load():
    with controller_instance.lock:
        total_delta = getattr(controller_instance, 'total_delta', 0)
        safe_delta = max(total_delta, 0)
        current_cpu = getattr(controller_instance, 'current_cpu', 0.0)
        current_mem = getattr(controller_instance, 'current_mem', 0.0)
        total_pkt_in = sum(controller_instance.packet_counts.get(dpid, 0) for dpid in controller_instance.datapaths)
    
    normalized_pkt_in = min(math.log1p(safe_delta) * 10, 100)
    score = round(controller_instance.a1 * current_cpu + controller_instance.a2 * current_mem + controller_instance.a3 * normalized_pkt_in, 2)
    return jsonify(cpu=current_cpu, mem=current_mem, pkt_in=total_pkt_in, score=score)
    
@flask_app.route('/switches')
def get_switches():
    return jsonify(sorted(controller_instance.owned_switches))

def start_flask():
    flask_app.run(port=8080, host="127.0.0.1", debug=False, use_reloader=False)

class LoadBalancingController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(LoadBalancingController, self).__init__(*args, **kwargs)
        self.name = "C1"
        self.datapaths = {}
        self.packet_counts = defaultdict(int)
        self.prev_packet_counts = {}
        # Modified: Multiple peer URLs for C2 and C3
        self.peer_urls = {
            "c2": "http://127.0.0.1:8081/load",
            "c3": "http://127.0.0.1:8082/load"
        }
        self.mac_to_port = {}
        self.lock = threading.Lock()
        self.current_cpu = 0.0
        self.current_mem = 0.0
        self.current_score = 0.0
        self.owned_switches = []
        # === Centralized score weights ===
        self.a1 = 0.1   # CPU weight
        self.a2 = 0.1   # Memory weight
        self.a3 = 0.8   # Packet_in weight
        global controller_instance
        controller_instance = self
        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()
        time.sleep(3)  # Allow Flask on other controllers to start
        
        self.monitor_thread = threading.Thread(target=self._monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        dpid_str = f"s{dpid}"
        
        self.logger.info("[C1] Register switch s%s", dpid)

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)                                  
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0,
                                match=match, instructions=inst)
        datapath.send_msg(mod)
        
        with self.lock:
            self.datapaths[dpid] = datapath
            self.packet_counts[dpid] = 0
            self.prev_packet_counts[dpid] = 0  # reset counters here
            self.owned_switches = list(self.datapaths.keys())
        
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        if dpid not in self.packet_counts:
            self.packet_counts[dpid] = 0
        self.packet_counts[dpid] += 1

        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return
        if eth.ethertype == ether_types.ETH_TYPE_ARP or eth.ethertype == ether_types.ETH_TYPE_IP:
            # self.logger.info(f"[C1] Packet_in: s{dpid}, in_port={in_port}, ethertype=0x{eth.ethertype:04x}")
            pass
        # ARP Handling
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                if arp_pkt.opcode == arp.ARP_REQUEST:
                    # self.logger.info(f"[C1] Handling ARP request {arp_pkt.src_ip} → {arp_pkt.dst_ip}")
                    pass
                elif arp_pkt.opcode == arp.ARP_REPLY:
                    # self.logger.info(f"[C1] Handling ARP reply {arp_pkt.src_ip} → {arp_pkt.dst_ip}")
                    pass
            self._handle_arp(datapath, in_port, pkt)
            return

        # IP Handling
        elif eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt is None:
                return

            dst_ip = ip_pkt.dst
            src_ip = ip_pkt.src
            # self.logger.info(f"[C1] Handling IP packet from {src_ip} → {dst_ip}")

            # MAC learning
            self.mac_to_port.setdefault(dpid, {})
            self.mac_to_port[dpid][eth.src] = in_port

            # Determine output port
            out_port = self.mac_to_port[dpid].get(eth.dst, ofproto.OFPP_FLOOD)
            actions = [parser.OFPActionOutput(out_port)]

            # ICMP Logging
            icmp_pkt = pkt.get_protocol(icmp.icmp)
            if icmp_pkt:
                # self.logger.info(f"[C1] ICMP packet: type={icmp_pkt.type}, code={icmp_pkt.code} from {src_ip} → {dst_ip}")
                pass

            # Flow Install (avoid flooding)
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_type=ether_types.ETH_TYPE_IP)
                self.add_flow(datapath, priority=1, match=match, actions=actions)
                # self.logger.info(f"[C1] Flow_mod: Installed IP flow s{dpid} {eth.src}  {eth.dst} via port {out_port}")

            # Packet Out
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=in_port,
                actions=actions,
                data=msg.data
            )
            datapath.send_msg(out)
            # self.logger.info(f"[C1] Packet_out: s{dpid} sent to port {out_port}")

        else:
            self.logger.debug(f"[C1] Unknown ethertype: 0x{eth.ethertype:04x}")

    def _monitor(self):
        # Ensure startup_time is set (fallback)
        if not hasattr(self, 'startup_time'):
            self.startup_time = time.time()
        if not hasattr(self, 'min_startup_delay'):
            self.min_startup_delay = 20
            
        log_file = "/tmp/kpi_log_c1_noLB.csv"

        # Create file with header if not exists
        if not os.path.exists(log_file):
            with open(log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "cpu", "memory", "packet_in_delta", "score"])
        time.sleep(5)
        self.prev_packet_counts = {}
        psutil.cpu_percent(interval=None)         # prime CPU counters
        process = psutil.Process(os.getpid())  # per-process memory
        while True:
            if not self.datapaths:
                hub.sleep(2)
                continue
            deltas = {}
            total_delta = 0
            
            for dpid in self.datapaths:
                current = self.packet_counts.get(dpid, 0)
                prev = self.prev_packet_counts.get(dpid, 0)
                delta = current - prev
                deltas[dpid] = delta
                total_delta += delta
                self.prev_packet_counts[dpid] = current

            with self.lock:
                self.total_delta = total_delta
                self.current_cpu = process.cpu_percent()      # process-level CPU %
                self.current_mem = process.memory_percent()   # process-level RAM %
            
            safe_delta = max(total_delta, 0)
            normalized_pkt_in = min(math.log1p(safe_delta) * 10, 100)

            score = round(self.a1 * self.current_cpu + self.a2 * self.current_mem + self.a3 * normalized_pkt_in, 2)

            switches = [f"s{dpid}" for dpid in self.datapaths]
            self.logger.info("[C1] CPU: %.1f%% | Memory: %.1f%% | pkt_in: %d | Score: %.2f | Switches: %s", 
                             self.current_cpu, self.current_mem, total_delta, score, switches)
            
            with self.lock:
                for dpid in self.datapaths:
                    delta = deltas.get(dpid, 0)
                    self.logger.info("[C1]  - s%s: packet_in delta = %d", dpid, delta)
                    
            # Append to CSV
            with open(log_file, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([time.time(), self.current_cpu, self.current_mem, total_delta, score])
            
            # === Get peer metrics from both C2 and C3 ===
            peer_scores = {}
            for peer_name, peer_url in self.peer_urls.items():
                try:
                    resp = requests.get(peer_url, timeout=2)
                    peer_data = resp.json()
                    peer_scores[peer_name] = float(peer_data.get("score", 0))
                except Exception as e:
                    self.logger.error("[C1] Error contacting %s: %s", peer_name, e)
                    peer_scores[peer_name] = 0  # Set to 0 for no-LB version
                
            # === Warm-up check ===
            if not peer_scores or all(s == 0 for s in peer_scores.values()):
                self.logger.info("[C1] Peer scores not ready, skipping migration decision.")
                hub.sleep(10)
                continue
                
            # === Startup delay check ===
            uptime = time.time() - self.startup_time
            if uptime < self.min_startup_delay:
                self.logger.info("[C1] Still in startup period (%.1fs), skipping migration", uptime)
                hub.sleep(10)
                continue
                
            # Find least loaded peer (for logging purposes only)
            valid_peers = {k: v for k, v in peer_scores.items() if v > 0}
            if valid_peers:
                min_peer = min(valid_peers.items(), key=lambda x: x[1])
                min_peer_name, min_peer_score = min_peer
                
                score_diff = abs(score - min_peer_score)
                self.logger.info("[C1] Score difference with %s: %.2f (Local: %.2f, Peer: %.2f)", 
                                min_peer_name, score_diff, score, min_peer_score)
                
                # === NO MIGRATION - Only logging ===
                if score > min_peer_score and score_diff > 7:
                    self.logger.info("[C1] Migration condition met, but load balancing is DISABLED for this test.")
                
            hub.sleep(3)
                         
    def _handle_arp(self, datapath, in_port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        arp_pkt = pkt.get_protocol(arp.arp)

        # Flood the ARP request for now
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port,
            actions=actions,
            data=pkt.data
        )
        datapath.send_msg(out)
        
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