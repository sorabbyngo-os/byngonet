//! dsoftbus/snap_transfer.rs
//!
//! Sorabbyngo Snap File Sharing + Hand-Motion Transfer protocol
//!
//! Snap transfer = grab current state of a file/app and throw it to
//! another device in one atomic operation. Like AirDrop but:
//!   - Works across all Sorabbyngo nodes (phone, laptop, server, IoT)
//!   - Transfers app STATE not just files (resume mid-task on another device)
//!   - Hand-motion triggered via wayland-shell gesture recognizer
//!   - Sub-second for files < 100MB over local network
//!
//! Hand-motion protocol (Iron Man style):
//!   PUSH gesture → file/app thrown to nearest screen
//!   PULL gesture → file/app pulled from nearest screen back
//!   SWIPE LEFT/RIGHT → file sent to specific device
//!   PINCH → shrink app to thumbnail, throw
//!   EXPAND → receive thumbnail, restore full app

use std::collections::HashMap;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

// ── Snap packet ────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct SnapManifest {
    pub snap_id:     [u8; 16],   // random UUID for this snap
    pub source_node: [u8; 32],   // NodeID of sender
    pub snap_type:   SnapType,
    pub name:        String,
    pub size_bytes:  u64,
    pub chunks:      u32,
    pub created_ns:  u64,
    pub checksum:    [u8; 32],   // BLAKE3 of full content
}

#[derive(Debug, Clone, PartialEq)]
pub enum SnapType {
    File,       // raw file transfer
    AppState,   // serialized app state (resume on target device)
    Clipboard,  // text/image clipboard content
    Screen,     // screen region projection
}

impl SnapType {
    pub fn as_u8(&self) -> u8 {
        match self {
            SnapType::File      => 0,
            SnapType::AppState  => 1,
            SnapType::Clipboard => 2,
            SnapType::Screen    => 3,
        }
    }
}

const CHUNK_SIZE: usize = 64 * 1024;  // 64KB chunks

// ── Snap sender ────────────────────────────────────────────────────────────

pub struct SnapSender {
    local_node_id: [u8; 32],
}

impl SnapSender {
    pub fn new(node_id: [u8; 32]) -> Self {
        Self { local_node_id: node_id }
    }

    /// Send a file to a remote node via an open StreamChannel
    pub fn send_file<W: Write>(
        &self,
        path: &Path,
        dest: &mut W,
    ) -> io::Result<SnapManifest> {
        let data     = fs::read(path)?;
        let name     = path.file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("unknown")
            .to_string();
        let checksum = self.checksum(&data);
        let snap_id  = self.new_snap_id();
        let chunks   = ((data.len() + CHUNK_SIZE - 1) / CHUNK_SIZE) as u32;

        let manifest = SnapManifest {
            snap_id,
            source_node: self.local_node_id,
            snap_type:   SnapType::File,
            name:        name.clone(),
            size_bytes:  data.len() as u64,
            chunks,
            created_ns:  now_ns(),
            checksum,
        };

        // Send manifest header
        let header = self.serialize_manifest(&manifest);
        dest.write_all(&(header.len() as u32).to_le_bytes())?;
        dest.write_all(&header)?;

        // Send data in chunks with sequence numbers
        for (i, chunk) in data.chunks(CHUNK_SIZE).enumerate() {
            dest.write_all(&(i as u32).to_le_bytes())?;
            dest.write_all(&(chunk.len() as u32).to_le_bytes())?;
            dest.write_all(chunk)?;
        }

        println!("[snap] sent {} ({} bytes, {} chunks) to remote",
            name, data.len(), chunks);

        Ok(manifest)
    }

    /// Send app state snapshot
    pub fn send_app_state<W: Write>(
        &self,
        app_name: &str,
        state:    &[u8],
        dest:     &mut W,
    ) -> io::Result<SnapManifest> {
        let checksum = self.checksum(state);
        let snap_id  = self.new_snap_id();
        let chunks   = ((state.len() + CHUNK_SIZE - 1) / CHUNK_SIZE) as u32;

        let manifest = SnapManifest {
            snap_id,
            source_node: self.local_node_id,
            snap_type:   SnapType::AppState,
            name:        app_name.to_string(),
            size_bytes:  state.len() as u64,
            chunks,
            created_ns:  now_ns(),
            checksum,
        };

        let header = self.serialize_manifest(&manifest);
        dest.write_all(&(header.len() as u32).to_le_bytes())?;
        dest.write_all(&header)?;

        for (i, chunk) in state.chunks(CHUNK_SIZE).enumerate() {
            dest.write_all(&(i as u32).to_le_bytes())?;
            dest.write_all(&(chunk.len() as u32).to_le_bytes())?;
            dest.write_all(chunk)?;
        }

        println!("[snap] sent app state '{}' ({} bytes)", app_name, state.len());
        Ok(manifest)
    }

    fn serialize_manifest(&self, m: &SnapManifest) -> Vec<u8> {
        let mut v = Vec::new();
        v.extend_from_slice(&m.snap_id);
        v.extend_from_slice(&m.source_node);
        v.push(m.snap_type.as_u8());
        let name_bytes = m.name.as_bytes();
        v.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        v.extend_from_slice(name_bytes);
        v.extend_from_slice(&m.size_bytes.to_le_bytes());
        v.extend_from_slice(&m.chunks.to_le_bytes());
        v.extend_from_slice(&m.created_ns.to_le_bytes());
        v.extend_from_slice(&m.checksum);
        v
    }

    fn checksum(&self, data: &[u8]) -> [u8; 32] {
        // Production: blake3::hash(data).into()
        let mut out = [0u8; 32];
        for (i, &b) in data.iter().enumerate() {
            out[i % 32] ^= b.wrapping_add(i as u8);
        }
        out
    }

    fn new_snap_id(&self) -> [u8; 16] {
        let ts = now_ns();
        let mut id = [0u8; 16];
        id[0..8].copy_from_slice(&ts.to_le_bytes());
        id[8..16].copy_from_slice(&self.local_node_id[0..8]);
        id
    }
}

// ── Snap receiver ──────────────────────────────────────────────────────────

pub struct SnapReceiver {
    output_dir: PathBuf,
}

impl SnapReceiver {
    pub fn new(output_dir: &Path) -> Self {
        fs::create_dir_all(output_dir).unwrap_or_default();
        Self { output_dir: output_dir.to_path_buf() }
    }

    pub fn receive<R: Read>(&self, src: &mut R) -> io::Result<SnapManifest> {
        // Read manifest
        let mut hlen_buf = [0u8; 4];
        src.read_exact(&mut hlen_buf)?;
        let hlen = u32::from_le_bytes(hlen_buf) as usize;
        let mut header = vec![0u8; hlen];
        src.read_exact(&mut header)?;
        let manifest = self.parse_manifest(&header)?;

        // Receive chunks
        let mut data = vec![0u8; manifest.size_bytes as usize];
        let mut received_chunks = 0u32;

        for _ in 0..manifest.chunks {
            let mut seq_buf = [0u8; 4];
            src.read_exact(&mut seq_buf)?;
            let seq = u32::from_le_bytes(seq_buf);

            let mut clen_buf = [0u8; 4];
            src.read_exact(&mut clen_buf)?;
            let clen = u32::from_le_bytes(clen_buf) as usize;

            let offset = seq as usize * CHUNK_SIZE;
            if offset + clen <= data.len() {
                src.read_exact(&mut data[offset..offset + clen])?;
            }
            received_chunks += 1;
        }

        // Save based on type
        match manifest.snap_type {
            SnapType::File | SnapType::AppState => {
                let out_path = self.output_dir.join(&manifest.name);
                fs::write(&out_path, &data)?;
                println!("[snap] received '{}' -> {:?}", manifest.name, out_path);
            }
            SnapType::Clipboard => {
                println!("[snap] clipboard received ({} bytes)", data.len());
                // Signal wayland-shell to update clipboard
            }
            SnapType::Screen => {
                println!("[snap] screen frame received ({} bytes)", data.len());
                // Forward to wayland-shell compositor
            }
        }

        Ok(manifest)
    }

    fn parse_manifest(&self, data: &[u8]) -> io::Result<SnapManifest> {
        if data.len() < 80 { return Err(io::Error::new(io::ErrorKind::InvalidData, "short manifest")); }
        let mut snap_id = [0u8; 16];
        snap_id.copy_from_slice(&data[0..16]);
        let mut source_node = [0u8; 32];
        source_node.copy_from_slice(&data[16..48]);
        let snap_type_byte = data[48];
        let name_len = u16::from_le_bytes(data[49..51].try_into().unwrap()) as usize;
        let name_end = 51 + name_len;
        let name = String::from_utf8_lossy(&data[51..name_end.min(data.len())]).to_string();
        let rest = &data[name_end..];
        let size_bytes  = u64::from_le_bytes(rest[0..8].try_into().unwrap_or_default());
        let chunks      = u32::from_le_bytes(rest[8..12].try_into().unwrap_or_default());
        let created_ns  = u64::from_le_bytes(rest[12..20].try_into().unwrap_or_default());
        let mut checksum = [0u8; 32];
        if rest.len() >= 52 { checksum.copy_from_slice(&rest[20..52]); }

        let snap_type = match snap_type_byte {
            0 => SnapType::File,
            1 => SnapType::AppState,
            2 => SnapType::Clipboard,
            3 => SnapType::Screen,
            _ => SnapType::File,
        };

        Ok(SnapManifest { snap_id, source_node, snap_type, name,
                          size_bytes, chunks, created_ns, checksum })
    }
}

// ── Hand-motion gesture protocol ───────────────────────────────────────────

#[derive(Debug, Clone)]
pub enum Gesture {
    Push { target_node: Option<[u8; 32]> },   // throw to nearest or specific
    Pull { source_node: Option<[u8; 32]> },   // pull from nearest or specific
    SwipeLeft  { target_node: [u8; 32] },
    SwipeRight { target_node: [u8; 32] },
    Pinch,    // minimize + prepare to throw
    Expand,   // receive + restore
}

#[derive(Debug)]
pub struct GestureEvent {
    pub gesture:    Gesture,
    pub snap_id:    Option<[u8; 16]>,
    pub timestamp:  u64,
}

/// GestureHandler — receives gesture events from wayland-shell
/// and triggers the appropriate snap transfer
pub struct GestureHandler {
    sender:   SnapSender,
    receiver: SnapReceiver,
    pending:  Option<Vec<u8>>,   // data held after Pinch, waiting for target
}

impl GestureHandler {
    pub fn new(node_id: [u8; 32], output_dir: &Path) -> Self {
        Self {
            sender:   SnapSender::new(node_id),
            receiver: SnapReceiver::new(output_dir),
            pending:  None,
        }
    }

    pub fn handle(&mut self, event: GestureEvent) {
        match event.gesture {
            Gesture::Pinch => {
                println!("[gesture] PINCH — grab current context, ready to throw");
                // wayland-shell will call snap_file() or snap_app_state()
                // and store in self.pending
            }
            Gesture::Push { target_node } => {
                println!("[gesture] PUSH -> {:?}", target_node);
                // In production: resolve nearest node if target_node is None
                // then call sender.send_file() or send_app_state()
            }
            Gesture::Pull { source_node } => {
                println!("[gesture] PULL <- {:?}", source_node);
                // Request snap from source_node via control channel
            }
            Gesture::SwipeLeft { target_node } => {
                println!("[gesture] SWIPE LEFT -> node {:?}", &target_node[0..4]);
            }
            Gesture::SwipeRight { target_node } => {
                println!("[gesture] SWIPE RIGHT -> node {:?}", &target_node[0..4]);
            }
            Gesture::Expand => {
                println!("[gesture] EXPAND — restore received snap");
                // Signal wayland-shell to restore the app from received state
            }
        }
    }
}

fn now_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
}
