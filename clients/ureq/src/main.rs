//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    let agent = ureq::Agent::new_with_defaults();
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        let mut r = agent.get(url).call().unwrap();
        status = r.status().as_u16();
        total += r.body_mut().read_to_vec().unwrap().len();
    }
    println!("{status} {total}");
}
