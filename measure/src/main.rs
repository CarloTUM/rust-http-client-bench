//! `measure <cmd> [args..]`: runs the command and prints one line to stderr,
//! `<wall µs> <cpu µs> <max RSS KiB>`, from `wait4`. Its own footprint is a
//! few hundred KiB, so it does not distort the child's peak RSS the way a
//! forked Python interpreter does.

use std::ffi::CString;
use std::time::Instant;

fn main() {
    let args: Vec<CString> = std::env::args()
        .skip(1)
        .map(|a| CString::new(a).unwrap())
        .collect();
    assert!(!args.is_empty(), "usage: measure <cmd> [args..]");
    let argv: Vec<*const libc::c_char> = args
        .iter()
        .map(|a| a.as_ptr())
        .chain(std::iter::once(std::ptr::null()))
        .collect();
    let start = Instant::now();
    // SAFETY: plain fork/exec/wait4 with valid NUL-terminated argv
    unsafe {
        let pid = libc::fork();
        if pid == 0 {
            let devnull = libc::open(c"/dev/null".as_ptr(), libc::O_WRONLY);
            libc::dup2(devnull, 1);
            libc::execvp(argv[0], argv.as_ptr());
            libc::_exit(127);
        }
        let mut status = 0;
        let mut usage: libc::rusage = std::mem::zeroed();
        libc::wait4(pid, &mut status, 0, &mut usage);
        let wall = start.elapsed().as_micros();
        let cpu = (usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) as i128 * 1_000_000
            + (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) as i128;
        eprintln!("{wall} {cpu} {}", usage.ru_maxrss);
        std::process::exit(if libc::WIFEXITED(status) { libc::WEXITSTATUS(status) } else { 1 });
    }
}
