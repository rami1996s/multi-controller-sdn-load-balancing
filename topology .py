# topology_3controller.py
from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink

class ThreeControllerTopology:
    def __init__(self):
        self.net = Mininet(controller=None, switch=OVSSwitch, link=TCLink)
        
        # Create 3 controllers
        self.c1 = self.net.addController('c1', controller=RemoteController, ip='127.0.0.1', port=6633)
        self.c2 = self.net.addController('c2', controller=RemoteController, ip='127.0.0.1', port=6634)
        self.c3 = self.net.addController('c3', controller=RemoteController, ip='127.0.0.1', port=6635)
        
        # Create 9 switches with OpenFlow 1.3 (4+2+3 distribution)
        self.switches = []
        for i in range(1, 10):
            self.switches.append(self.net.addSwitch(f's{i}', protocols='OpenFlow13'))
        
        # Create 54 hosts (6 per switch)
        self.hosts = [self.net.addHost(f'h{i}', ip=f'10.0.0.{i}/24') for i in range(1, 55)]
        
        # Connect hosts to switches (6 hosts per switch)
        for sw_idx in range(9):
            for h_idx in range(6):
                host_index = sw_idx * 6 + h_idx
                self.net.addLink(self.switches[sw_idx], self.hosts[host_index])
        
        # Connect switches in a linear topology: s1-s2-s3-s4-s5-s6-s7-s8-s9
        for i in range(8):  # connect s1-s2, s2-s3, ..., s8-s9
            self.net.addLink(self.switches[i], self.switches[i+1], bw=100, delay='1ms')

    def start(self):
        self.net.build()
        
        # Start controllers
        self.c1.start()
        self.c2.start()
        self.c3.start()
        
        # Start switches with their initial controllers
        # C1 manages 4 switches: s1, s2, s3, s4
        self.switches[0].start([self.c1])  # s1
        self.switches[1].start([self.c1])  # s2
        self.switches[2].start([self.c1])  # s3
        self.switches[3].start([self.c1])  # s4
        
        # C2 manages 2 switches: s5, s6
        self.switches[4].start([self.c2])  # s5
        self.switches[5].start([self.c2])  # s6
        
        # C3 manages 3 switches: s7, s8, s9
        self.switches[6].start([self.c3])  # s7
        self.switches[7].start([self.c3])  # s8
        self.switches[8].start([self.c3])  # s9
        
        # Enable networking on hosts
        self._enable_networking()
        
        info("3-Controller network ready. Initial assignment:\n")
        info("- C1 (port 6633): s1, s2, s3, s4 (24 hosts)\n")
        info("- C2 (port 6634): s5, s6 (12 hosts)\n") 
        info("- C3 (port 6635): s7, s8, s9 (18 hosts)\n")
        info("Use 'pingall' manually when needed.\n")
        
        return self.net

    def _enable_networking(self):
        for host in self.hosts:
            host.cmd('sysctl -w net.ipv4.ip_forward=1')
            host.cmd('ip link set dev %s mtu 1500' % host.defaultIntf())
            host.cmd('arp -d -a >/dev/null 2>&1')
            host.cmd('ping -c 1 10.0.0.255 >/dev/null 2>&1 &')

if __name__ == '__main__':
    setLogLevel('info')
    topo = ThreeControllerTopology()
    net = topo.start()
    
    try:
        CLI(net)
    finally:
        net.stop()