//! Native desktop controls. One preview dispatcher and bounded requests keep
//! scrubbing responsive even when exact RF simulation is slower than playback.
use crate::{
    gst_media::GstVideoSource,
    media::{self, ExportOptions},
    model::{self, Params, Spec},
    preview,
    preview_clock::PlaybackClock,
    renderer::{self, FieldMode, FrameOutput, Generation},
    signal::{HEIGHT, WIDTH},
};
use eframe::egui::{self, Color32, RichText};
use rustfft::{num_complex::Complex, FftPlanner};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc::{self, Receiver, SyncSender},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

const BG: Color32 = Color32::from_rgb(14, 22, 22);
const PANEL: Color32 = Color32::from_rgb(23, 34, 36);
const MINT: Color32 = Color32::from_rgb(156, 218, 192);
const MUTED: Color32 = Color32::from_rgb(167, 186, 187);
const AMBER: Color32 = Color32::from_rgb(238, 198, 119);

pub fn run(initial_video: Option<PathBuf>, params: Params, workers: usize) -> Result<(), String> {
    let icon = eframe::icon_data::from_png_bytes(include_bytes!("../assets/icons/pal-vhs.png"))
        .map_err(|error| format!("Cannot load the app icon: {error}"))?;
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("PAL VHS · Cassette Edition")
            .with_icon(icon)
            .with_inner_size([1360.0, 900.0])
            .with_min_inner_size([900.0, 650.0]),
        ..Default::default()
    };
    eframe::run_native(
        "PAL VHS · Cassette Edition",
        options,
        Box::new(move |cc| Ok(Box::new(App::new(cc, initial_video, params, workers)))),
    )
    .map_err(|e| e.to_string())
}

struct PreviewRequest {
    id: u64,
    path: PathBuf,
    frame: u64,
    params: Params,
    scopes: bool,
}
struct PreviewResponse {
    id: u64,
    frame: u64,
    result: Result<PreviewData, String>,
}
struct PreviewData {
    output: FrameOutput,
    n_frames: u64,
    duration: f64,
    rf_ms: f64,
}
struct ExportJob {
    cancel: Arc<AtomicBool>,
    done: Arc<AtomicU64>,
    total: Arc<AtomicU64>,
    rx: Receiver<Result<(), String>>,
    path: PathBuf,
}

fn preview_worker(ctx: egui::Context) -> (SyncSender<PreviewRequest>, Receiver<PreviewResponse>) {
    let (tx, requests) = mpsc::sync_channel::<PreviewRequest>(1);
    let (responses, rx) = mpsc::sync_channel(1);
    thread::Builder::new()
        .name("pal-vhs-preview".into())
        .spawn(move || {
            let mut source: Option<(PathBuf, GstVideoSource)> = None;
            let mut cached_engine: Option<(Value, preview::AccuratePreview)> = None;
            while let Ok(job) = requests.recv() {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    if source.as_ref().map(|s| &s.0) != Some(&job.path) {
                        cached_engine = None; // RGB cache must not cross source clips.
                        source = Some((job.path.clone(), GstVideoSource::open(&job.path)?));
                    }
                    let video = &mut source.as_mut().unwrap().1;
                    let (first, second) = video.fields(job.frame, &job.params)?;
                    let key = job.params.to_value();
                    if cached_engine.as_ref().map(|e| &e.0) != Some(&key) {
                        cached_engine = Some((key, preview::AccuratePreview::new(job.params.clone())?));
                    }
                    let rf_start = Instant::now();
                    let output = cached_engine.as_mut().unwrap().1.render(
                        &first,
                        &second,
                        job.frame,
                        FieldMode::from_params(&job.params),
                        job.scopes,
                    )?;
                    let rf_ms = rf_start.elapsed().as_secs_f64() * 1000.0;
                    Ok(PreviewData {
                        output,
                        n_frames: video.info.n_frames,
                        duration: video.info.duration,
                        rf_ms,
                    })
                }))
                .unwrap_or_else(|_| {
                    Err("Preview renderer panicked; retry to recreate its state.".into())
                });
                if result.is_err() {
                    source = None;
                    cached_engine = None;
                }
                if responses
                    .send(PreviewResponse {
                        id: job.id,
                        frame: job.frame,
                        result,
                    })
                    .is_err()
                {
                    break;
                }
                ctx.request_repaint();
            }
        })
        .expect("preview worker thread");
    (tx, rx)
}

struct App {
    params: Params,
    path: Option<PathBuf>,
    frame: u64,
    n_frames: u64,
    duration: f64,
    tx: SyncSender<PreviewRequest>,
    rx: Receiver<PreviewResponse>,
    generation: Generation,
    pending: Option<PreviewRequest>,
    busy: bool,
    texture: Option<egui::TextureHandle>,
    displayed_frame: Option<u64>,
    taps: BTreeMap<String, Vec<f64>>,
    advanced: bool,
    search: String,
    preset: String,
    deck: String,
    history: Vec<Value>,
    error: Option<String>,
    preview_failed: bool,
    status: String,
    playing: bool,
    playback_clock: PlaybackClock,
    realtime: bool,
    scopes: bool,
    scope_tap: String,
    scope_line: usize,
    scope_wave: Vec<[f64; 2]>,
    scope_spectrum: Vec<[f64; 2]>,
    scope_dirty: bool,
    export: Option<ExportJob>,
    export_dialog: bool,
    export_options: ExportOptions,
    export_path: Option<PathBuf>,
}
impl App {
    fn new(
        cc: &eframe::CreationContext<'_>,
        path: Option<PathBuf>,
        params: Params,
        workers: usize,
    ) -> Self {
        let mut style = (*cc.egui_ctx.style()).clone();
        style.visuals = egui::Visuals::dark();
        style.visuals.panel_fill = BG;
        style.visuals.window_fill = PANEL;
        style.visuals.override_text_color = Some(Color32::from_rgb(226, 236, 231));
        style.visuals.widgets.inactive.bg_fill = PANEL;
        style.visuals.widgets.inactive.bg_stroke =
            egui::Stroke::new(1.0_f32, Color32::from_rgb(64, 88, 80));
        style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(42, 65, 59);
        style.visuals.selection.bg_fill = Color32::from_rgb(45, 94, 75);
        style.visuals.selection.stroke = egui::Stroke::new(1.5_f32, MINT);
        style.spacing.item_spacing = egui::vec2(8.0, 8.0);
        style.spacing.button_padding = egui::vec2(12.0, 7.0);
        style.spacing.interact_size.y = 28.0;
        style
            .text_styles
            .insert(egui::TextStyle::Body, egui::FontId::proportional(14.0));
        cc.egui_ctx.set_style(style);
        let (tx, rx) = preview_worker(cc.egui_ctx.clone());
        let mut app = Self {
            params,
            path,
            frame: 0,
            n_frames: 1,
            duration: 0.0,
            tx,
            rx,
            generation: Generation::default(),
            pending: None,
            busy: false,
            texture: None,
            displayed_frame: None,
            taps: BTreeMap::new(),
            advanced: false,
            search: String::new(),
            preset: "PAL VHS / SP - fresh cassette".into(),
            deck: "Domestic 2-head / aligned".into(),
            history: Vec::new(),
            error: None,
            preview_failed: false,
            status: "Open a video to begin".into(),
            playing: false,
            playback_clock: PlaybackClock::new(),
            realtime: true,
            scopes: false,
            scope_tap: "comp_out".into(),
            scope_line: 100,
            scope_wave: Vec::new(),
            scope_spectrum: Vec::new(),
            scope_dirty: true,
            export: None,
            export_dialog: false,
            export_options: ExportOptions {
                workers,
                ..Default::default()
            },
            export_path: None,
        };
        app.request_preview();
        app
    }
    fn toggle_playback(&mut self) {
        if self.playing {
            if self.realtime {
                self.frame = self.playback_clock.target(Instant::now(), self.n_frames);
            }
            self.playing = false;
            self.changed();
        } else {
            if self.frame + 1 >= self.n_frames && self.n_frames > 1 {
                self.frame = 0;
                self.request_preview();
            }
            self.playing = true;
            self.playback_clock.start(self.frame, Instant::now());
        }
    }
    fn fail(&mut self, message: String) {
        self.error = Some(message);
    }
    fn changed(&mut self) {
        self.preview_failed = false;
        if self.playing {
            self.playback_clock.start(self.frame, Instant::now());
        } else {
            self.playback_clock.seek(self.frame, Instant::now());
            self.playback_clock.pause();
        }
        self.request_preview();
    }
    fn request_preview(&mut self) {
        let id = self.generation.advance();
        if let Some(path) = self.path.clone() {
            self.pending = Some(PreviewRequest {
                id,
                path,
                frame: self.frame,
                params: self.params.clone(),
                scopes: self.scopes,
            });
        }
    }
    fn poll(&mut self, ctx: &egui::Context) {
        while let Ok(reply) = self.rx.try_recv() {
            self.busy = false;
            if !self.generation.accepts(reply.id) {
                continue;
            }
            match reply.result {
                Ok(data) => {
                    self.n_frames = data.n_frames.max(1);
                    self.duration = data.duration;
                    self.frame = self.frame.min(self.n_frames - 1);
                    let image = egui::ColorImage::from_rgb([WIDTH, HEIGHT], &data.output.rgb);
                    if let Some(texture) = &mut self.texture {
                        texture.set(image, egui::TextureOptions::LINEAR);
                    } else {
                        self.texture = Some(ctx.load_texture(
                            "video-preview",
                            image,
                            egui::TextureOptions::LINEAR,
                        ));
                    }
                    self.displayed_frame = Some(reply.frame);
                    self.taps = data.output.taps;
                    self.scope_dirty = true;
                    self.status = format!(
                        "720 × 576 · 25 fps timeline · {:.2} s · {} · exact RF {:.0} ms/frame",
                        self.duration,
                        if FieldMode::from_params(&self.params).is_interlaced() {
                            "Interlaced TFF"
                        } else {
                            "Progressive"
                        },
                        data.rf_ms
                    );
                }
                Err(e) => {
                    self.preview_failed = true;
                    self.playing = false;
                    self.fail(format!("Preview failed: {e}"));
                }
            }
        }
        if let Some(job) = &self.export {
            if let Ok(result) = job.rx.try_recv() {
                let path = job.path.clone();
                let cancelled = job.cancel.load(Ordering::Relaxed);
                self.export = None;
                match result {
                    Ok(()) => self.status = format!("Export saved: {}", path.display()),
                    Err(_e) if cancelled => self.status = "Export cancelled".into(),
                    Err(e) => self.fail(format!("Export failed: {e}")),
                }
            }
        }
        if self.playing && !self.busy && self.pending.is_none() {
            let target = if self.realtime {
                self.playback_clock.target(Instant::now(), self.n_frames)
            } else {
                (self.frame + 1).min(self.n_frames.saturating_sub(1))
            };
            if target > self.frame {
                self.frame = target;
                self.request_preview();
            } else if self.frame + 1 >= self.n_frames {
                self.playing = false;
                self.playback_clock.pause();
            }
        }
        if !self.busy && !self.preview_failed {
            if let Some(job) = self.pending.take() {
                match self.tx.try_send(job) {
                    Ok(()) => self.busy = true,
                    Err(mpsc::TrySendError::Full(job)) => self.pending = Some(job),
                    Err(mpsc::TrySendError::Disconnected(_)) => {
                        self.preview_failed = true;
                        self.fail("Preview worker stopped. Restart the application.".into());
                    }
                }
            }
        }
        if self.busy || self.playing || self.export.is_some() {
            ctx.request_repaint_after(Duration::from_millis(if self.playing { 5 } else { 16 }));
        }
    }
    fn remember(&mut self, before: Value) {
        let now = self.params.to_value();
        let difference = before
            .as_object()
            .unwrap()
            .iter()
            .filter(|(k, v)| now.get(*k) != Some(*v))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect::<serde_json::Map<String, Value>>();
        if !difference.is_empty() {
            self.history.push(Value::Object(difference));
            if self.history.len() > 20 {
                self.history.remove(0);
            }
        }
    }
    fn damage(&mut self, action: &str) {
        if action == "undo" {
            if let Some(patch) = self.history.pop() {
                if let Err(e) = self.params.update(&patch) {
                    self.fail(e);
                }
                self.changed();
            }
            return;
        }
        let before = self.params.to_value();
        let result = match action {
            "smear" | "crease" => self
                .params
                .set_macro(action, self.params.macro_position(action) + 15.0),
            "dropouts" => self.params.set(
                "dropout_rate",
                json!(self.params.number("dropout_rate") + 2.0),
            ),
            "white" => self
                .params
                .set("wr_travel", json!(!self.params.boolean("wr_travel"))),
            "repair" => (|| {
                for key in ["wear", "smear", "crease"] {
                    self.params.set_macro(key, 0.0)?;
                }
                self.params
                    .update(&json!({"tracking":0,"wr_travel":false,"snow_sparse":0}))
            })(),
            _ => Ok(()),
        };
        if let Err(e) = result {
            self.fail(e);
        }
        self.remember(before);
        self.changed();
    }
    fn open(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .add_filter(
                "Video",
                &[
                    "mp4", "mov", "mkv", "avi", "webm", "m4v", "mpeg", "mpg", "ts",
                ],
            )
            .pick_file()
        {
            self.path = Some(path);
            self.frame = 0;
            self.n_frames = 1;
            self.duration = 0.0;
            self.playing = false;
            self.texture = None;
            self.displayed_frame = None;
            self.error = None;
            self.status = "Opening video…".into();
            self.taps.clear();
            self.scope_dirty = true;
            self.changed();
        }
    }
    fn settings(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if ui.button("Save settings…").clicked() {
                if let Some(path) = rfd::FileDialog::new()
                    .add_filter("JSON settings", &["json"])
                    .set_file_name("pal-vhs-settings.json")
                    .save_file()
                {
                    match self.params.save(&path) {
                        Ok(()) => self.status = format!("Settings saved: {}", path.display()),
                        Err(e) => self.fail(e),
                    }
                }
            }
            if ui.button("Load…").clicked() {
                if let Some(path) = rfd::FileDialog::new()
                    .add_filter("JSON settings", &["json"])
                    .pick_file()
                {
                    match Params::load(path) {
                        Ok(params) => {
                            self.params = params;
                            self.history.clear();
                            self.changed();
                        }
                        Err(e) => self.fail(e),
                    }
                }
            }
            if ui
                .button("Defaults")
                .on_hover_text("Restore all factory parameters")
                .clicked()
            {
                self.params = Params::default();
                self.history.clear();
                self.changed();
            }
        });
    }
    fn cassette(&self, ui: &mut egui::Ui) {
        let (rect, _) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), 132.0),
            egui::Sense::hover(),
        );
        let p = ui.painter();
        p.rect_filled(rect.shrink(1.0), 10.0, PANEL);
        p.rect_stroke(
            rect.shrink(1.0),
            10.0,
            egui::Stroke::new(1.0_f32, Color32::from_rgb(77, 101, 106)),
            egui::StrokeKind::Inside,
        );
        let label = egui::Rect::from_min_size(
            rect.min + egui::vec2(16.0, 12.0),
            egui::vec2(rect.width() - 32.0, 28.0),
        );
        p.rect_filled(label, 3.0, Color32::from_rgb(207, 208, 185));
        p.text(
            label.center(),
            egui::Align2::CENTER_CENTER,
            format!(
                "PAL  /  {}     HOME VIDEO",
                self.params.choice("tape_speed")
            ),
            egui::FontId::proportional(14.0),
            BG,
        );
        for x in [0.28, 0.72] {
            let c = egui::pos2(rect.left() + rect.width() * x, rect.top() + 78.0);
            p.circle_filled(c, 25.0, BG);
            p.circle_stroke(c, 25.0, egui::Stroke::new(1.0_f32, MUTED));
            p.circle_filled(c, 9.0, MUTED);
        }
        p.text(
            egui::pos2(rect.center().x, rect.bottom() - 15.0),
            egui::Align2::CENTER_CENTER,
            "V H S   ·   625 / 50   ·   COLOUR UNDER",
            egui::FontId::proportional(11.0),
            MUTED,
        );
    }
    fn easy(&mut self, ui: &mut egui::Ui) {
        self.cassette(ui);
        ui.label(RichText::new("YOUR TAPE, YOUR DAMAGE").color(MINT).strong());
        ui.label("Choose a tape, then tune its character.");
        ui.label("Playback deck");
        egui::ComboBox::from_id_salt("deck")
            .width(ui.available_width() - 20.0)
            .selected_text(&self.deck)
            .show_ui(ui, |ui| {
                for name in model::decks().keys() {
                    ui.selectable_value(&mut self.deck, name.clone(), name);
                }
            });
        if ui.button("Apply deck").on_hover_text("Changes playback settings only; keeps tape condition and source. Undo reverses this action.").clicked(){let before=self.params.to_value();if let Err(e)=self.params.apply_deck(&self.deck){self.fail(e);}self.remember(before);self.changed();}
        if self.params.boolean("bypass_tape") {
            ui.colored_label(AMBER, "VHS bypass is on. Tape controls are hidden.");
            if ui.button("Turn VHS bypass off").clicked() {
                let _ = self.params.set("bypass_tape", json!(false));
                self.changed();
            }
        } else {
        if let Some(spec) = model::specs().iter().find(|s| s.key == "tape_speed") {
            if parameter(ui, &mut self.params, spec) {
                self.changed();
            }
        }
        ui.separator();
        for name in ["wear", "colour", "unstable", "smear", "crease"] {
            let meta = &model::macros()[name];
            let mut amount = self.params.macro_position(name);
            ui.label(meta[0].as_str().unwrap_or(name));
            if ui
                .add(
                    egui::Slider::new(&mut amount, 0.0..=100.0)
                        .suffix(" %")
                        .integer(),
                )
                .on_hover_text(meta[1].as_str().unwrap_or(""))
                .changed()
            {
                if let Err(e) = self.params.set_macro(name, amount) {
                    self.fail(e);
                }
                self.changed();
            }
        }
        ui.separator();
        if self.params.choice("hs_model") == "RF switch" {
            ui.label("Head-switch snow");
            let mut strength = self.params.number("hs_residual") * 100.0;
            if ui
                .add(egui::Slider::new(&mut strength, 0.0..=100.0).suffix(" %"))
                .on_hover_text(
                    "Visible narrow head-switch snow. Width, height and motion are in Advanced.",
                )
                .changed()
            {
                let _ = self.params.set("hs_residual", json!(strength / 100.0));
                self.changed();
            }
            if self.params.is_active("hs_residual_follow") {
                let mut follow = self.params.boolean("hs_residual_follow");
                if ui
                    .checkbox(&mut follow, "Follow head-switch line")
                    .on_hover_text(
                        "Puts the top snow line on the first line hit by the head switch instead of a fixed gap from the bottom.",
                    )
                    .changed()
                {
                    let _ = self.params.set("hs_residual_follow", json!(follow));
                    self.changed();
                }
                let mut moving = self.params.choice("hs_residual_motion") != "Stationary";
                if ui
                    .checkbox(&mut moving, "Moving snow")
                    .on_hover_text("Moves the snow patch horizontally as frames advance.")
                    .changed()
                {
                    let _ = self.params.set(
                        "hs_residual_motion",
                        json!(if moving { "Drift + jitter" } else { "Stationary" }),
                    );
                    self.changed();
                }
            }
        }
        let mut tracking = self.params.number("tracking");
        ui.label("Tracking − / +");
        if ui
            .add(egui::Slider::new(&mut tracking, -1.0..=1.0).fixed_decimals(2))
            .on_hover_text("0 = aligned; negative adds bottom noise, positive top noise.")
            .changed()
        {
            let _ = self.params.set("tracking", json!(tracking));
            self.changed();
        }
        egui::Grid::new("damage-buttons").num_columns(2).spacing([8.0,8.0]).show(ui,|ui|{
            for (i,(label,action)) in [("+ Smear","smear"),("+ Crease","crease"),("+ Dropouts","dropouts"),("White band","white"),("Undo damage","undo"),("Repair damage","repair")].iter().enumerate(){if ui.add_enabled(*action!="undo"||!self.history.is_empty(),egui::Button::new(*label).min_size(egui::vec2(144.0,30.0))).on_hover_text("Applies repeatable damage to the entire clip. Undo restores the last button action.").clicked(){self.damage(action);}if i%2==1{ui.end_row();}}
        });
        ui.label(format!(
            "White bands: {} · Dropouts: {:.1}/frame",
            if self.params.boolean("wr_travel") {
                "ON"
            } else {
                "OFF"
            },
            self.params.number("dropout_rate")
        ));
        }
        ui.label(RichText::new("Macros edit their own Advanced parameter families. Damage is repeatable when seeking and exporting.").small().color(MUTED));
    }
    fn advanced(&mut self, ui: &mut egui::Ui) {
        ui.add(
            egui::TextEdit::singleline(&mut self.search)
                .hint_text("Search parameters, groups or help…")
                .desired_width(f32::INFINITY),
        );
        let query = self.search.to_lowercase();
        let mut groups: BTreeMap<&str, Vec<&Spec>> = BTreeMap::new();
        let mut hidden = 0;
        for spec in model::specs() {
            if query.is_empty()
                || format!("{} {} {} {}", spec.key, spec.label, spec.group, spec.tip)
                    .to_lowercase()
                    .contains(&query)
            {
                // Controls whose parent switch, model or strength is off are hidden.
                if self.params.is_active(&spec.key) {
                    groups.entry(&spec.group).or_default().push(spec);
                } else {
                    hidden += 1;
                }
            }
        }
        if groups.is_empty() {
            ui.label("No matching parameters.");
        }
        if hidden > 0 && !query.is_empty() {
            ui.label(
                RichText::new(format!(
                    "{hidden} matching parameter(s) hidden because the setting that enables them is off."
                ))
                .small()
                .color(MUTED),
            );
        }
        if self.params.boolean("bypass_tape") && query.is_empty() {
            ui.colored_label(
                AMBER,
                "VHS bypass is on: tape, head-switch, dropout and playback groups are hidden.",
            );
        }
        let mut edited = false;
        for (group, specs) in groups {
            egui::CollapsingHeader::new(group)
                .open(if query.is_empty() { None } else { Some(true) })
                .show(ui, |ui| {
                    for spec in specs {
                        edited |= parameter(ui, &mut self.params, spec);
                        ui.add_space(3.0);
                    }
                });
        }
        if edited {
            self.changed();
        }
    }
    fn controls(&mut self, ui: &mut egui::Ui) {
        ui.heading(RichText::new("CASSETTE DECK").color(MINT));
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.advanced, false, "Easy");
            ui.selectable_value(&mut self.advanced, true, "Advanced");
        });
        ui.separator();
        ui.label("Tape preset");
        egui::ComboBox::from_id_salt("preset")
            .width(ui.available_width() - 20.0)
            .selected_text(&self.preset)
            .show_ui(ui, |ui| {
                for name in model::presets().keys() {
                    ui.selectable_value(&mut self.preset, name.clone(), name);
                }
            });
        if ui
            .button("Apply tape preset")
            .on_hover_text("Replaces all parameters, including playback settings")
            .clicked()
        {
            if let Err(e) = self.params.apply_preset(&self.preset) {
                self.fail(e);
            }
            self.history.clear();
            self.changed();
        }
        self.settings(ui);
        ui.separator();
        if self.advanced {
            self.advanced(ui);
        } else {
            self.easy(ui);
        }
    }
    fn transport(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui|{
            if ui.button("Open video…").clicked(){self.open();}
            let enabled=self.path.is_some()&&!self.preview_failed;
            if ui.add_enabled(enabled,egui::Button::new(if self.playing{"Pause"}else{"Play"})).clicked(){self.toggle_playback();}
            if ui.add_enabled(enabled&&self.frame>0,egui::Button::new("Previous")).clicked(){self.playing=false;self.frame=self.frame.saturating_sub(1);self.changed();}
            if ui.add_enabled(enabled&&self.frame+1<self.n_frames,egui::Button::new("Next")).clicked(){self.playing=false;self.frame=(self.frame+1).min(self.n_frames-1);self.changed();}
            if ui.checkbox(&mut self.realtime,"25 fps clock").on_hover_text("Follow elapsed time and skip late preview frames. Disable to inspect every frame as fast as rendering allows.").changed(){self.playback_clock.start(self.frame,Instant::now());}
            if ui.add_enabled(self.path.is_some()&&self.export.is_none(),egui::Button::new("Export…")).clicked(){self.export_dialog=true;}
        });
        let response = ui
            .add_enabled_ui(self.path.is_some(), |ui| {
                ui.spacing_mut().slider_width = (ui.available_width() - 75.0).max(100.0);
                ui.add(
                    egui::Slider::new(&mut self.frame, 0..=self.n_frames.saturating_sub(1))
                        .show_value(false)
                        .text("Timeline"),
                )
            })
            .inner;
        if response.changed() {
            self.playing = false;
            self.changed();
        }
        ui.horizontal(|ui| {
            ui.monospace(format!(
                "{:02}:{:02}.{:02}  /  {:.2} s    Frame {} / {}",
                self.frame / 1500,
                (self.frame / 25) % 60,
                (self.frame % 25) * 4,
                self.duration,
                self.frame,
                self.n_frames.saturating_sub(1)
            ));
            if self.busy {
                ui.spinner();
                ui.label("Rendering");
            }
            if let Some(shown) = self.displayed_frame {
                if shown != self.frame {
                    ui.colored_label(AMBER, format!("Showing frame {shown}"));
                }
            }
        });
        ui.label(RichText::new(&self.status).small().color(MUTED));
    }
    fn start_export(&mut self, path: PathBuf, ctx: &egui::Context) {
        let Some(input) = self.path.clone() else {
            return;
        };
        let cancel = Arc::new(AtomicBool::new(false));
        let done = Arc::new(AtomicU64::new(0));
        let total = Arc::new(AtomicU64::new(0));
        let (tx, rx) = mpsc::sync_channel(1);
        let job = ExportJob {
            cancel: cancel.clone(),
            done: done.clone(),
            total: total.clone(),
            rx,
            path: path.clone(),
        };
        let options = self.export_options.clone();
        let params = self.params.clone();
        let ctx = ctx.clone();
        thread::Builder::new()
            .name("pal-vhs-export".into())
            .spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    media::export_video(&input, &path, params, options, cancel, |n, t| {
                        done.store(n, Ordering::Relaxed);
                        total.store(t, Ordering::Relaxed);
                        ctx.request_repaint();
                    })
                }))
                .unwrap_or_else(|_| Err("Export worker panicked. Retry the export.".into()));
                let _ = tx.send(result);
                ctx.request_repaint();
            })
            .expect("export worker thread");
        self.export = Some(job);
        self.export_dialog = false;
    }
    fn export_window(&mut self, ctx: &egui::Context) {
        if !self.export_dialog {
            return;
        }
        let mut open = true;
        let mut start = false;
        egui::Window::new("Export PAL video")
            .open(&mut open)
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.label("Exact signal export · independent of preview mode");
                ui.label("720 × 576 · 25 fps · 4:3 display aspect");
                ui.label(if FieldMode::from_params(&self.params).is_interlaced() {
                    "Woven fields · top field first"
                } else {
                    "Selected field · line-doubled progressive"
                });
                ui.label("Field output mode is set in Advanced / Input.");
                ui.label(".mp4 = H.264, progressive (plays everywhere) · .mov = ProRes HQ, interlaced (for editors)");
                ui.separator();
                ui.horizontal(|ui| {
                    ui.label("Start frame");
                    ui.add(
                        egui::DragValue::new(&mut self.export_options.start_frame)
                            .range(0..=self.n_frames.saturating_sub(1)),
                    );
                });
                let mut limited = self.export_options.max_frames.is_some();
                if ui.checkbox(&mut limited, "Limit frame count").changed() {
                    self.export_options.max_frames = if limited {
                        Some(self.n_frames.min(250))
                    } else {
                        None
                    };
                }
                if let Some(max) = &mut self.export_options.max_frames {
                    ui.add(egui::DragValue::new(max).range(1..=self.n_frames.max(1)));
                }
                ui.add(
                    egui::Slider::new(&mut self.export_options.crf, 0..=40)
                        .text("H.264 CRF (lower = higher quality)"),
                );
                egui::ComboBox::from_label("Encoder preset")
                    .selected_text(&self.export_options.x264_preset)
                    .show_ui(ui, |ui| {
                        for name in [
                            "ultrafast",
                            "superfast",
                            "veryfast",
                            "faster",
                            "fast",
                            "medium",
                            "slow",
                            "slower",
                            "veryslow",
                        ] {
                            ui.selectable_value(
                                &mut self.export_options.x264_preset,
                                name.into(),
                                name,
                            );
                        }
                    });
                ui.horizontal(|ui| {
                    ui.label("Render workers");
                    ui.add(egui::DragValue::new(&mut self.export_options.workers).range(1..=64));
                });
                ui.checkbox(
                    &mut self.export_options.audio,
                    "Pass source audio through unchanged",
                );
                if ui.button("Choose destination…").clicked() {
                    self.export_path = rfd::FileDialog::new()
                        .add_filter("MP4 video (H.264)", &["mp4"])
                        .add_filter("MOV (ProRes, for editors)", &["mov"])
                        .set_file_name("pal-vhs-export.mp4")
                        .save_file();
                }
                if let Some(path) = &self.export_path {
                    ui.label(path.display().to_string());
                }
                if ui
                    .add_enabled(
                        self.export_path.is_some(),
                        egui::Button::new("Start export"),
                    )
                    .clicked()
                {
                    start = true;
                }
            });
        self.export_dialog = open;
        if start {
            if let Some(path) = self.export_path.clone() {
                self.start_export(path, ctx);
            }
        }
    }
    fn update_scope(&mut self) {
        if !self.scope_dirty {
            return;
        }
        self.scope_dirty = false;
        self.scope_wave.clear();
        self.scope_spectrum.clear();
        let Some(tap) = self.taps.get(&self.scope_tap) else {
            return;
        };
        let fi = usize::from(FieldMode::from_params(&self.params) == FieldMode::Second);
        let lines = if fi == 0 { 313 } else { 312 };
        let samples = tap.len() / lines;
        if samples == 0 {
            return;
        }
        let start = self.scope_line.min(lines - 1) * samples;
        let line = &tap[start..(start + samples).min(tap.len())];
        self.scope_wave = line
            .iter()
            .enumerate()
            .step_by((samples / 1800).max(1))
            .map(|(i, &y)| [i as f64 * 64.0 / samples as f64, y])
            .collect();
        let n = if samples >= 2048 { 2048 } else { 1024 };
        if line.len() < n {
            return;
        }
        let mut buffer: Vec<Complex<f64>> = line[..n]
            .iter()
            .enumerate()
            .map(|(i, &y)| {
                Complex::new(
                    y * (0.5
                        - 0.5 * (2.0 * std::f64::consts::PI * i as f64 / (n - 1) as f64).cos()),
                    0.0,
                )
            })
            .collect();
        FftPlanner::<f64>::new()
            .plan_fft_forward(n)
            .process(&mut buffer);
        let sample_mhz = samples as f64 / 64.0;
        self.scope_spectrum = buffer[..n / 2]
            .iter()
            .enumerate()
            .map(|(i, v)| {
                [
                    i as f64 * sample_mhz / n as f64,
                    (v.norm() * 4.0 / n as f64).max(1e-7).log10() * 20.0,
                ]
            })
            .collect();
    }
    fn scope_panel(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("SIGNAL SCOPES").color(MINT).strong());
            egui::ComboBox::from_id_salt("scope-tap")
                .selected_text(&self.scope_tap)
                .show_ui(ui, |ui| {
                    for key in [
                        "comp_in",
                        "comp_out",
                        "rec_luma",
                        "fm",
                        "tape",
                        "c_under",
                        "luma_demod",
                        "c_out",
                        "rf_env",
                    ] {
                        if ui
                            .selectable_value(&mut self.scope_tap, key.into(), key)
                            .changed()
                        {
                            self.scope_dirty = true;
                        }
                    }
                });
            ui.label("Field line");
            if ui
                .add(egui::DragValue::new(&mut self.scope_line).range(0..=311))
                .changed()
            {
                self.scope_dirty = true;
            }
        });
        self.update_scope();
        if self.taps.get(&self.scope_tap).is_none() {
            ui.label("No tap available. Tape stages require VHS bypass off.");
        }
        ui.columns(2, |columns| {
            columns[0].label("Line waveform · µs / volts");
            egui_plot::Plot::new("waveform")
                .height(155.0)
                .include_x(0.0)
                .include_x(64.0)
                .show(&mut columns[0], |plot| {
                    plot.line(egui_plot::Line::new(self.scope_wave.clone()).color(MINT));
                });
            columns[1].label("Hann spectrum · MHz / dB amplitude");
            egui_plot::Plot::new("spectrum")
                .height(155.0)
                .include_y(-90.0)
                .include_y(0.0)
                .show(&mut columns[1], |plot| {
                    plot.line(egui_plot::Line::new(self.scope_spectrum.clone()).color(AMBER));
                });
        });
    }
}

fn parameter(ui: &mut egui::Ui, params: &mut Params, spec: &Spec) -> bool {
    let mut value = None;
    ui.push_id(&spec.key, |ui| {
        let label = ui.label(&spec.label);
        label.on_hover_text(format!(
            "{}\nKey: {} · Default: {}",
            spec.tip, spec.key, spec.default
        ));
        match spec.kind.as_str() {
            "bool" => {
                let mut v = params.boolean(&spec.key);
                if ui
                    .checkbox(&mut v, "Enabled")
                    .on_hover_text(&spec.tip)
                    .changed()
                {
                    value = Some(json!(v));
                }
            }
            "choice" => {
                let mut v = params.choice(&spec.key).to_owned();
                egui::ComboBox::from_id_salt("choice")
                    .width(ui.available_width() - 20.0)
                    .selected_text(&v)
                    .show_ui(ui, |ui| {
                        if let Some(options) = spec.lo.as_ref().and_then(Value::as_array) {
                            for option in options {
                                if let Some(option) = option.as_str() {
                                    if ui
                                        .selectable_value(&mut v, option.to_owned(), option)
                                        .changed()
                                    {
                                        value = Some(json!(v));
                                    }
                                }
                            }
                        }
                    })
                    .response
                    .on_hover_text(&spec.tip);
            }
            _ => {
                let mut v = params.number(&spec.key);
                let lo = spec.lo.as_ref().and_then(Value::as_f64).unwrap_or(0.0);
                let hi = spec.hi.as_ref().and_then(Value::as_f64).unwrap_or(1.0);
                let mut slider =
                    egui::Slider::new(&mut v, lo..=hi).step_by(spec.step.unwrap_or(0.01));
                if spec.kind == "int" {
                    slider = slider.integer();
                }
                if ui
                    .add(slider)
                    .on_hover_text(format!(
                        "{}\nRange: {} … {}. Click the value to type exactly.",
                        spec.tip, lo, hi
                    ))
                    .changed()
                {
                    value = Some(json!(v));
                }
            }
        }
    });
    value
        .map(|value| params.set(&spec.key, value).is_ok())
        .unwrap_or(false)
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll(ctx);
        if ctx.input(|i| i.modifiers.command && i.key_pressed(egui::Key::O)) {
            self.open();
        }
        if !ctx.wants_keyboard_input()
            && !self.export_dialog
            && self.path.is_some()
            && !self.preview_failed
        {
            let direction = ctx.input(|i| {
                if i.key_pressed(egui::Key::ArrowLeft) {
                    -1
                } else if i.key_pressed(egui::Key::ArrowRight) {
                    1
                } else {
                    0
                }
            });
            if direction != 0 {
                self.playing = false;
                self.frame = if direction < 0 {
                    self.frame.saturating_sub(1)
                } else {
                    (self.frame + 1).min(self.n_frames.saturating_sub(1))
                };
                self.changed();
            }
        }
        if ctx.input(|i| i.key_pressed(egui::Key::Space))
            && !ctx.wants_keyboard_input()
            && self.path.is_some()
            && !self.preview_failed
        {
            self.toggle_playback();
        }
        egui::TopBottomPanel::top("title").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new("PAL / VHS").size(20.0).strong().color(MINT));
                ui.label(RichText::new("CASSETTE EDITION").color(MUTED));
                ui.separator();
                ui.add(
                    egui::Label::new(
                        self.path
                            .as_ref()
                            .and_then(|p| p.file_name())
                            .map(|n| n.to_string_lossy().into_owned())
                            .unwrap_or_else(|| "No video loaded".into()),
                    )
                    .truncate(),
                )
                .on_hover_text(
                    self.path
                        .as_ref()
                        .map(|p| p.display().to_string())
                        .unwrap_or_default(),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(
                        RichText::new("ACCURATE · FULL PAL/VHS RF")
                            .small()
                            .color(MUTED),
                    );
                });
            });
        });
        egui::TopBottomPanel::bottom("transport").show(ctx, |ui| {
            self.transport(ui);
            if let Some(job) = &self.export {
                let done = job.done.load(Ordering::Relaxed);
                let total = job.total.load(Ordering::Relaxed);
                let cancelling = job.cancel.load(Ordering::Relaxed);
                let text = if cancelling {
                    "Cancelling export…".into()
                } else if total == 0 {
                    "Preparing export…".into()
                } else if done >= total {
                    "Finalizing export…".into()
                } else {
                    format!("Exporting {done} / {total} frames")
                };
                ui.horizontal(|ui| {
                    ui.add(
                        egui::ProgressBar::new(if total > 0 {
                            done as f32 / total as f32
                        } else {
                            0.0
                        })
                        .desired_width(360.0)
                        .animate(total == 0)
                        .text(text),
                    );
                    if ui
                        .add_enabled(!cancelling, egui::Button::new("Cancel export"))
                        .clicked()
                    {
                        job.cancel.store(true, Ordering::Relaxed);
                    }
                });
            }
            if let Some(error) = self.error.clone() {
                ui.horizontal_wrapped(|ui| {
                    ui.colored_label(Color32::from_rgb(255, 155, 133), error);
                    if ui.button("Dismiss").clicked() {
                        self.error = None;
                    }
                });
            }
            if self.preview_failed && ui.button("Retry preview").clicked() {
                self.error = None;
                self.preview_failed = false;
                self.request_preview();
            }
        });
        egui::SidePanel::left("parameters")
            .resizable(true)
            .default_width(390.0)
            .width_range(340.0..=560.0)
            .show(ctx, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.controls(ui));
            });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new("MONITOR").color(MINT).strong());
                if ui.checkbox(&mut self.scopes, "Signal scopes")
                    .on_hover_text("Scopes from the exact PAL/VHS waveform renderer.")
                    .changed()
                {
                    self.changed();
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(RichText::new("4:3 · PAL 625 / 50").small().color(MUTED));
                });
            });
            if self.scopes {
                egui::TopBottomPanel::bottom("scopes-inner")
                    .resizable(true)
                    .default_height(225.0)
                    .show_inside(ui, |ui| self.scope_panel(ui));
            }
            let available = ui.available_size();
            let size = egui::vec2(
                available.x.min(available.y * 4.0 / 3.0),
                available.y.min(available.x * 3.0 / 4.0),
            );
            ui.allocate_ui_with_layout(
                available,
                egui::Layout::centered_and_justified(egui::Direction::TopDown),
                |ui| {
                    if let Some(texture) = &self.texture {
                        ui.add(egui::Image::new(texture).fit_to_exact_size(size));
                    } else {
                        ui.label(
                            RichText::new(if self.busy {
                                "Preparing PAL preview…"
                            } else {
                                "Open a video to load your virtual cassette"
                            })
                            .size(20.0)
                            .color(MUTED),
                        );
                    }
                },
            );
        });
        self.export_window(ctx);
    }
}
impl Drop for App {
    fn drop(&mut self) {
        if let Some(job) = &self.export {
            job.cancel.store(true, Ordering::Relaxed);
        }
    }
}
