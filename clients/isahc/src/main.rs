//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
use std::io::Read;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    let client = isahc::HttpClient::new().unwrap();
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        let mut r = client.get(url).unwrap();
        status = r.status().as_u16();
        let mut buf = Vec::new();
        r.body_mut().read_to_end(&mut buf).unwrap();
        total += buf.len();
    }
    println!("{status} {total}");
}
