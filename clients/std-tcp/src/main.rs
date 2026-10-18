//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
//! The floor without a library: `std::net::TcpStream`, a hand-written request
//! line and a Content-Length read, one keep-alive connection. Plain HTTP only;
//! an `https://` URL exits with code 3 ("unsupported") and the table shows `-`.
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    let Some(rest) = url.strip_prefix("http://") else {
        std::process::exit(3);
    };
    let (host_port, path) = rest.split_once('/').map_or((rest, "/"), |(h, p)| (h, &rest[h.len()..]));
    let authority = if host_port.contains(':') { host_port.to_owned() } else { format!("{host_port}:80") };
    let stream = TcpStream::connect(&authority).unwrap();
    stream.set_nodelay(true).unwrap();
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    let mut stream = stream;
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        write!(stream, "GET {path} HTTP/1.1\r\nHost: {host_port}\r\n\r\n").unwrap();
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        status = line.split_whitespace().nth(1).unwrap().parse().unwrap();
        let mut length = 0usize;
        loop {
            line.clear();
            reader.read_line(&mut line).unwrap();
            let h = line.trim_end();
            if h.is_empty() {
                break;
            }
            if let Some(v) = h.to_ascii_lowercase().strip_prefix("content-length:") {
                length = v.trim().parse().unwrap();
            }
        }
        let mut body = vec![0; length];
        reader.read_exact(&mut body).unwrap();
        total += body.len();
    }
    println!("{status} {total}");
}
