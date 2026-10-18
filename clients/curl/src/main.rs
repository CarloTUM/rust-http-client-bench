//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    // One easy handle for the whole process, like every other client keeps
    // one connection pool: libcurl reuses the connection between requests.
    let mut easy = curl::easy::Easy::new();
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        easy.url(url).unwrap();
        let mut body = Vec::new();
        {
            let mut t = easy.transfer();
            t.write_function(|d| {
                body.extend_from_slice(d);
                Ok(d.len())
            })
            .unwrap();
            t.perform().unwrap();
        }
        status = easy.response_code().unwrap() as u16;
        total += body.len();
    }
    println!("{status} {total}");
}
