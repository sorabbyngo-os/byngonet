//! dsoftbus/discovery.rs
//!
//! Sorabbyngo DSoftBus — auto-discovery protocol
//!
//! Devices announce themselves via UDP multicast on startup.
//! Every node listens, builds a peer table, and opens a
//! PIN-authenticated channel within 100ms of first seeing a peer.
//!
//! Announcement packet (64 bytes):
//!   [0..4]   magic: 0x42 0x59 0x4E 0x47  ("BYNG")
//!   [4..36]  node_id: [u8; 32]  — hardware-rooted NodeID
//!   [6..52]  capabilities: u64  — bitmask of what this node offers
//!   [52..60] timestamp_ns: u64
//!   [60..64] crc32: u32

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, UdpSocket};
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const DISCOVERY_MULTICAST: Ipv4Addr = Ipv4Addr::new(239, 255, 42, 99);
pub const DISCOVERY_PORT: u16 = 7429;
pub const ANNOUNCE_MAGIC: [u8; 4] = [0x42, 0x59, 0x4E, 0x47];
pub const ANNOUNCE_INTERVAL: Duration = Duration::from_secs(5);
pub const PEER_TIMEOUT: Duration = Duration::from_secs(30);

// Capability bitmask — what a node can offer to the pool
pub const CAP_GPU_COMPUTE:  u64 = 1 << 0;
pub const CAP_GPU_RENDER:   u64 = 1 << 1;
pub const CAP_CAMERA:       u64 = 1 << 2;
pub const CAP_MICROPHONE:   u64 = 1 << 3;
pub const CAP_DISPLAY:      u64 = 1 << 4;
pub const CAP_SENSOR_IMU:   u64 = 1 << 5;
pub const CAP_STORAGE:      u64 = 1 << 6;
pub const CAP_AI_INFERENCE: u64 = 1 << 7;

#[derive(Debug, Clone)]
pub struct Peer {
    pub node_id:      [u8; 32],
    pub addr:         IpAddr,
    pub capabilities: u64,
    pub last_seen:    Instant,
    pub latency_ns:   u64,   // measured round-trip / 2
    pub pin_verified: bool,
}

impl Peer {
    pub fn has_cap(&self, cap: u64) -> bool {
        self.capabilities & cap != 0
    }

    pub fn is_alive(&self) -> bool {
        self.last_seen.elapsed() < PEER_TIMEOUT
    }

    pub fn node_id_hex(&self) -> String {
        self.node_id.iter().map(|b| format!("{:02x}", b)).collect()
    }
}

pub struct DiscoveryService {
    local_node_id:    [u8; 32],
    local_caps:       u64,
    peers:            Arc<RwLock<HashMap<[u8; 32], Peer>>>,
}

impl DiscoveryService {
    pub fn new(node_id: [u8; 32], caps: u64) -> Self {
        Self {
            local_node_id: node_id,
            local_caps:    caps,
            peers:         Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub fn peers(&self) -> Arc<RwLock<HashMap<[u8; 32], Peer>>> {
        Arc::clone(&self.peers)
    }

    /// Build the 64-byte announcement packet
    fn build_announce(&self) -> [u8; 64] {
        let mut pkt = [0u8; 64];
        pkt[0..4].copy_from_slice(&ANNOUNCE_MAGIC);
        pkt[4..36].copy_from_slice(&self.local_node_id);
        pkt[36..44].copy_from_slice(&self.local_caps.to_le_bytes());
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos() as u64;
        pkt[44..52].copy_from_slice(&ts.to_le_bytes());
        // CRC32 over bytes 0..60
        let crc = crc32_simple(&pkt[0..60]);
        pkt[60..64].copy_from_slice(&crc.to_le_bytes());
        pkt
    }

    /// Parse an incoming announcement packet
    fn parse_announce(buf: &[u8], from: IpAddr) -> Option<Peer> {
        if buf.len() < 64 { return None; }
        if buf[0..4] != ANNOUNCE_MAGIC { return None; }

        // Verify CRC
        let expected_crc = crc32_simple(&buf[0..60]);
        let got_crc = u32::from_le_bytes(buf[60..64].try_into().ok()?);
        if expected_crc != got_crc { return None; }

        let mut node_id = [0u8; 32];
        node_id.copy_from_slice(&buf[4..36]);
        let capabilities = u64::from_le_bytes(buf[36..44].try_into().ok()?);

        Some(Peer {
            node_id,
            addr:         from,
            capabilities,
            last_seen:    Instant::now(),
            latency_ns:   0,
            pin_verified: false,
        })
    }

    /// Announce loop — broadcast every ANNOUNCE_INTERVAL
    pub fn start_announce(&self) -> std::thread::JoinHandle<()> {
        let pkt = self.build_announce();
        std::thread::spawn(move || {
            let sock = UdpSocket::bind("0.0.0.0:0").expect("announce socket");
            let dest = SocketAddr::new(
                IpAddr::V4(DISCOVERY_MULTICAST), DISCOVERY_PORT);
            loop {
                let _ = sock.send_to(&pkt, dest);
                std::thread::sleep(ANNOUNCE_INTERVAL);
            }
        })
    }

    /// Listen loop — receive announcements, update peer table
    pub fn start_listen(&self) -> std::thread::JoinHandle<()> {
        let peers = Arc::clone(&self.peers);
        let local_id = self.local_node_id;
        std::thread::spawn(move || {
            let sock = UdpSocket::bind(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), DISCOVERY_PORT))
                .expect("listen socket");
            sock.join_multicast_v4(&DISCOVERY_MULTICAST, &Ipv4Addr::UNSPECIFIED)
                .expect("multicast join");
            sock.set_read_timeout(Some(Duration::from_secs(2))).ok();

            let mut buf = [0u8; 64];
            loop {
                match sock.recv_from(&mut buf) {
                    Ok((n, from)) if n >= 64 => {
                        if let Some(peer) = Self::parse_announce(&buf, from.ip()) {
                            // Don't add ourselves
                            if peer.node_id == local_id { continue; }

                            let is_new = {
                                let r = peers.read().unwrap();
                                !r.contains_key(&peer.node_id)
                            };

                            if is_new {
                                println!("[dsoftbus] new peer: {} caps={:#x}",
                                    peer.node_id_hex(), peer.capabilities);
                            }

                            peers.write().unwrap()
                                .insert(peer.node_id, peer);
                        }
                    }
                    _ => {
                        // Prune dead peers
                        peers.write().unwrap()
                            .retain(|_, p| p.is_alive());
                    }
                }
            }
        })
    }
}

// Minimal CRC32 (no external deps)
fn crc32_simple(data: &[u8]) -> u32 {
    let mut crc: u32 = 0xFFFFFFFF;
    for &b in data {
        crc ^= b as u32;
        for _ in 0..8 {
            if crc & 1 != 0 { crc = (crc >> 1) ^ 0xEDB88320; }
            else             { crc >>= 1; }
        }
    }
    !crc
}
