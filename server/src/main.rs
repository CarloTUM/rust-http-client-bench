//! Minimal HTTP/1.1 keep-alive server for the benchmarks: `/small` is 1 KiB,
//! `/big` is 8 MiB, `/echo` echoes a POST body. No dependencies, one thread
//! per connection.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;

fn main() {
    let addr = std::env::args().nth(1).unwrap_or_else(|| "127.0.0.1:8080".into());
    let listener = TcpListener::bind(&addr).unwrap();
    eprintln!("bench-server on http://{addr}");
    let small = vec![b'a'; 1024];
    let big = vec![b'b'; 8 * 1024 * 1024];
    for conn in listener.incoming().flatten() {
        let (small, big) = (small.clone(), big.clone());
        thread::spawn(move || serve(conn, &small, &big));
    }
}

fn serve(mut conn: TcpStream, small: &[u8], big: &[u8]) {
    conn.set_nodelay(true).ok();
    let mut reader = BufReader::new(conn.try_clone().unwrap());
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).unwrap_or(0) == 0 {
            return;
        }
        let path = line.split_whitespace().nth(1).unwrap_or("/").to_owned();
        let mut length = 0usize;
        let mut close = false;
        loop {
            let mut h = String::new();
            if reader.read_line(&mut h).unwrap_or(0) == 0 {
                return;
            }
            let h = h.trim_end();
            if h.is_empty() {
                break;
            }
            let lower = h.to_ascii_lowercase();
            if let Some(v) = lower.strip_prefix("content-length:") {
                length = v.trim().parse().unwrap_or(0);
            }
            if lower == "connection: close" {
                close = true;
            }
        }
        let mut body = vec![0; length];
        if reader.read_exact(&mut body).is_err() {
            return;
        }
        let payload: &[u8] = match path.as_str() {
            "/big" => big,
            "/echo" => &body,
            _ => small,
        };
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: {}\r\n\r\n",
            payload.len()
        );
        if conn.write_all(head.as_bytes()).is_err() || conn.write_all(payload).is_err() {
            return;
        }
        if close {
            return;
        }
    }
}
