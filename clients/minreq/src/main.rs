//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        let r = minreq::get(url).send().unwrap();
        status = r.status_code as u16;
        total += r.as_bytes().len();
    }
    println!("{status} {total}");
}
