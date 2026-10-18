//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
//! The floor of the floor: a Rust binary that only prints "0 0". What the
//! process itself costs (exec, dynamic loader, libc and std init), so that the
//! other rows can be read as "on top of this".
fn main() {
    println!("0 0");
}
