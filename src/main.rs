use clap::Parser;
use pal_vhs::{
    media::{self, ExportOptions},
    model::{self, Params},
};
use std::{
    path::PathBuf,
    sync::{atomic::AtomicBool, Arc},
    time::Instant,
};

#[derive(Parser, Debug)]
#[command(
    version,
    about = "PAL VHS cassette deck — native Rust signal simulator"
)]
struct Args {
    /// Input video; omit to open an empty cassette deck.
    video: Option<PathBuf>,
    /// Render offline instead of opening the desktop application.
    #[arg(long, value_name = "OUTPUT")]
    export: Option<PathBuf>,
    #[arg(long)]
    preset: Option<String>,
    #[arg(long, value_name = "FILE.json")]
    params: Option<PathBuf>,
    /// Override a setting; may be repeated.
    #[arg(long = "set", value_name = "KEY=VALUE")]
    overrides: Vec<String>,
    #[arg(long)]
    list_params: bool,
    #[arg(long)]
    list_presets: bool,
    #[arg(long)]
    save_params: Option<PathBuf>,
    #[arg(long)]
    workers: Option<usize>,
    /// Compatibility flag; native Rust always uses threads.
    #[arg(long,value_parser=["thread","process"])]
    render_backend: Option<String>,
    #[arg(long)]
    max_frames: Option<u64>,
    #[arg(long, default_value_t = 0)]
    start_frame: u64,
    #[arg(long)]
    no_audio: bool,
    #[arg(long,default_value_t=14,value_parser=clap::value_parser!(u8).range(0..=51))]
    crf: u8,
    #[arg(long, default_value = "veryfast")]
    x264_preset: String,
}

fn run() -> Result<(), String> {
    let args = Args::parse();
    if args.list_params {
        for s in model::specs() {
            println!(
                "{:<27} {:<12} {}  {}",
                s.key,
                s.default,
                s.lo.as_ref()
                    .map(|v| format!("{v}..{}", s.hi.as_ref().unwrap_or(&serde_json::Value::Null)))
                    .unwrap_or_default(),
                s.label
            );
        }
        return Ok(());
    }
    if args.list_presets {
        for name in model::presets().keys() {
            println!("{name}");
        }
        return Ok(());
    }
    let mut params = match args.params {
        Some(path) => Params::load(path)?,
        None => Params::default(),
    };
    if let Some(preset) = args.preset {
        params.apply_preset(&preset)?;
    }
    for override_ in args.overrides {
        let (key, text) = override_
            .split_once('=')
            .ok_or_else(|| format!("Expected KEY=VALUE, got {override_}"))?;
        let spec = model::specs()
            .iter()
            .find(|s| s.key == key)
            .ok_or_else(|| format!("Unknown parameter {key}; use --list-params"))?;
        let value = match spec.kind.as_str() {
            "bool" => serde_json::json!(match text.to_ascii_lowercase().as_str() {
                "1" | "true" | "yes" | "on" => true,
                "0" | "false" | "no" | "off" => false,
                _ => return Err(format!("{key}: expected true or false")),
            }),
            "float" | "int" => {
                let n = text
                    .parse::<f64>()
                    .map_err(|_| format!("{key}: expected a number"))?;
                if !n.is_finite() {
                    return Err(format!("{key}: expected a finite number"));
                }
                serde_json::json!(n)
            }
            _ => serde_json::json!(text),
        };
        params.set(key, value)?;
    }
    let workers = args.workers.unwrap_or(ExportOptions::default().workers);
    if workers == 0 || workers > 64 {
        return Err("Workers must be between 1 and 64".into());
    }
    if let Some(path) = args.save_params {
        params.save(path)?;
        if args.export.is_none() {
            return Ok(());
        }
    }
    if args.render_backend.as_deref() == Some("process") {
        eprintln!("Native Rust uses threads; --render-backend process is accepted for command compatibility.");
    }
    if let Some(output) = args.export {
        let input = args.video.ok_or("--export requires an input video")?;
        let options = ExportOptions {
            workers,
            start_frame: args.start_frame,
            max_frames: args.max_frames,
            audio: !args.no_audio,
            crf: args.crf,
            x264_preset: args.x264_preset,
        };
        let begin = Instant::now();
        media::export_video(
            &input,
            &output,
            params,
            options,
            Arc::new(AtomicBool::new(false)),
            |done, total| {
                let elapsed = begin.elapsed().as_secs_f64();
                eprint!(
                    "\r{done}/{total} frames  {:.2} fps  {elapsed:.1}s",
                    done as f64 / elapsed.max(0.001)
                );
            },
        )?;
        eprintln!("\nWrote {}", output.display());
        return Ok(());
    }
    #[cfg(feature = "desktop")]
    {
        pal_vhs::gui::run(args.video, params, workers)
    }
    #[cfg(not(feature = "desktop"))]
    {
        Err("Desktop support was disabled in this build. Use --export or rebuild with default features.".into())
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}
