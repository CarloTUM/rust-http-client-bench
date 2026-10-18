//! GET <url> [-n count]: one process, `count` sequential requests on one
//! client, prints status and total bytes. Identical across clients.
//! hyper 1 with the `legacy` connection pool from hyper-util and TLS from
//! hyper-rustls, the way reqwest does it underneath, on a current-thread runtime.
use http_body_util::{BodyExt, Empty};
use hyper::body::Bytes;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let url = &args[1];
    let n: usize = args.get(3).map_or(1, |s| s.parse().unwrap());
    let https = hyper_rustls::HttpsConnectorBuilder::new()
        .with_native_roots()
        .unwrap()
        .https_or_http()
        .enable_http1()
        .build();
    let client: Client<_, Empty<Bytes>> = Client::builder(TokioExecutor::new()).build(https);
    let uri: hyper::Uri = url.parse().unwrap();
    let mut total = 0;
    let mut status = 0;
    for _ in 0..n {
        let r = client.get(uri.clone()).await.unwrap();
        status = r.status().as_u16();
        total += r.into_body().collect().await.unwrap().to_bytes().len();
    }
    println!("{status} {total}");
}
