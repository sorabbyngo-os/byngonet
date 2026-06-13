//! Sorabbyngo DSoftBus — main entry point
//!
//! Starts all DSoftBus subsystems:
//!   - Discovery (UDP multicast)
//!   - StarShield (Zero Trust)
//!   - Super Device pool
//!   - HMAF orchestrator
//!   - Snap transfer server
//!   - Channel manager

mod discovery;
mod transport;
mod snap_transfer;
mod superdevice;
mod hmaf;
mod starshield;

use discovery::{DiscoveryService, CAP_GPU_COMPUTE, CAP_AI_INFERENCE,
                CAP_STORAGE, CAP_DISPLAY};
use superdevice::{SuperDevice, VirtualDeviceType};
use hmaf::HmafOrchestrator;
use starshield::TrustStore;

use std::time::Duration;

fn main() {
    println!("╔═══════════════════════════════════════╗");
    println!("║  Sorabbyngo DSoftBus — starting up    ║");
    println!("╚═══════════════════════════════════════╝");

    // 1. StarShield — derive NodeID from hardware
    let mut trust = TrustStore::new();
    let node_id   = trust.local_node_id();
    println!("[main] NodeID: {}", node_id[0..8]
        .iter().map(|b| format!("{:02x}", b)).collect::<String>());

    // 2. Discovery — announce capabilities and listen for peers
    let local_caps = CAP_GPU_COMPUTE | CAP_AI_INFERENCE | CAP_STORAGE | CAP_DISPLAY;
    let discovery  = DiscoveryService::new(node_id, local_caps);
    let peers      = discovery.peers();

    let _announce_thread = discovery.start_announce();
    let _listen_thread   = discovery.start_listen();
    println!("[main] discovery started — multicast 239.255.42.99:7429");

    // 3. Super Device pool — register local hardware
    let mut superdevice = SuperDevice::new(node_id);
    superdevice.register_local_hardware();

    // 4. HMAF — register the byngox agent types
    let mut hmaf = HmafOrchestrator::new(node_id);
    hmaf.register_agent("health-agent",      "health");
    hmaf.register_agent("drug-agent",        "drug");
    hmaf.register_agent("context-agent",     "context");
    hmaf.register_agent("network-agent",     "network");
    hmaf.register_agent("learning-agent",    "learning");
    hmaf.register_agent("population-agent",  "population");
    hmaf.register_agent("security-agent",    "security");
    hmaf.register_agent("inference-agent",   "inference");

    println!("[main] HMAF — {} agents registered", hmaf.agent_count());
    println!("[main] Super Device — {}", superdevice.pool_summary());

    // 5. Main loop — register new peers as they appear
    println!("[main] running — waiting for peers...");
    let mut last_peer_count = 0;

    loop {
        std::thread::sleep(Duration::from_secs(2));

        let peer_count = peers.read().unwrap().len();
        if peer_count != last_peer_count {
            println!("[main] peers: {}", peer_count);

            // Register new peers in Super Device pool
            let peer_list: Vec<_> = peers.read().unwrap()
                .values().cloned().collect();

            for peer in &peer_list {
                if !peer.pin_verified {
                    // Auto-verify peers on local network (no PIN for local discovery)
                    // Production: require PIN for cross-network peers
                    trust.verify_peer(peer.node_id, true);
                }
                superdevice.register_peer(peer);
            }

            println!("[main] {}", superdevice.pool_summary());
            trust.print_status();
            last_peer_count = peer_count;
        }
    }
}
