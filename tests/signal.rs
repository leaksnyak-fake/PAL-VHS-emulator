use pal_vhs::{
    dsp,
    model::Params,
    signal::{Engine, FIELD_HEIGHT, WIDTH},
};
use serde_json::json;

#[test]
fn fm_discriminator_maps_sync_and_white() {
    for (volts, hz) in [(-0.3, 3.8e6), (0.7, 4.8e6)] {
        let x = dsp::fm_mod(&vec![volts; 32768], 3.8e6, 1e6, 35_468_750.0, None);
        let (f, _) = dsp::fm_demod(&x, 35_468_750.0);
        let avg = f[4096..28672].iter().sum::<f64>() / 24576.0;
        assert!((avg - hz).abs() < 100.0, "{avg} != {hz}");
    }
}

#[test]
fn causal_filters_preserve_dc_and_reject_high_frequency() {
    let filter = dsp::lowpass(1e6, 4, 17_734_375.0);
    let y = filter.run(&vec![0.7; 1000]);
    assert!(y.iter().all(|v| (v - 0.7).abs() < 1e-10));
    assert!(filter.response(4e6, 17_734_375.0).norm() < 0.01);
}

#[test]
fn analytic_group_delay_matches_scipy() {
    let fs = 17_734_375.0;
    for (filter, frequency, expected) in [
        (dsp::lowpass(0.55e6, 3, fs), 0.05e6, 10.274690680165772),
        (
            dsp::bandpass(4_433_618.75 - 1.4e6, 4_433_618.75 + 1.4e6, 2, fs),
            4_433_618.75,
            2.6134196832523475,
        ),
        (
            dsp::notch(4_433_618.75, 2.5, fs),
            0.5e6,
            0.33420132929819957,
        ),
    ] {
        let actual = filter.group_delay(frequency, fs);
        assert!((actual - expected).abs() < 1e-10, "{actual} != {expected}");
    }
}

#[test]
fn field_timing_and_deterministic_seeking() {
    let mut p = Params::default();
    p.set("rf_rate", json!("1x")).unwrap();
    let mut e = Engine::new(p).unwrap();
    let input = vec![128; WIDTH * FIELD_HEIGHT * 3];
    let a = e.render_field(&input, 0, 3, true).unwrap();
    e.render_field(&input, 1, 29, false).unwrap();
    let b = e.render_field(&input, 0, 3, true).unwrap();
    assert_eq!(a.rgb, b.rgb);
    assert_eq!(a.taps, b.taps);
    assert_eq!(a.taps["comp_in"].len(), 313 * 1135);
    assert_eq!(a.rgb.len(), input.len());
    assert!(a.taps.values().flatten().all(|x| x.is_finite()));
    let sync = &a.taps["comp_in"];
    assert!((sync[10 * 1135 + 30] + 0.3).abs() < 1e-6);
}

#[test]
fn early_head_switch_sync_does_not_black_out_picture() {
    let mut p = Params::default();
    p.set("hs_model", json!("RF switch")).unwrap();
    p.set("hs_shift_us", json!(-20)).unwrap();
    p.set("hs_noise", json!(0)).unwrap();
    p.set("hs_phase_deg", json!(0)).unwrap();
    p.set("hs_mask_lines", json!(0)).unwrap();
    let input = vec![192; WIDTH * FIELD_HEIGHT * 3];
    let engine = Engine::new(p).unwrap();
    for field in 0..2 {
        let out = engine.render_field(&input, field, 0, false).unwrap();
        for line in FIELD_HEIGHT - 3..FIELD_HEIGHT {
            let center = (line * WIDTH + WIDTH / 2) * 3;
            assert!(
                out.rgb[center..center + 3].iter().all(|&c| c > 100),
                "field {field}, line {line}: {:?}",
                &out.rgb[center..center + 3]
            );
        }
    }
}

#[test]
fn head_phase_mismatch_does_not_modify_recording_taps() {
    let mut p = Params::default();
    p.set("rf_rate", json!("1x")).unwrap();
    p.set("hs_model", json!("RF switch")).unwrap();
    p.set("hs_phase_deg", json!(0)).unwrap();
    let input = vec![150; WIDTH * FIELD_HEIGHT * 3];
    let a = Engine::new(p.clone())
        .unwrap()
        .render_field(&input, 0, 0, true)
        .unwrap();
    p.set("hs_phase_deg", json!(120)).unwrap();
    let b = Engine::new(p)
        .unwrap()
        .render_field(&input, 0, 0, true)
        .unwrap();
    assert_eq!(a.taps["fm"], b.taps["fm"]);
    assert_eq!(a.taps["rec_luma"], b.taps["rec_luma"]);
    assert_ne!(a.taps["tape"], b.taps["tape"]);
}

#[test]
fn tape_bypass_still_encodes_and_decodes_pal() {
    let mut p = Params::default();
    p.set("bypass_tape", json!(true)).unwrap();
    p.set("out_noise", json!(0)).unwrap();
    let input = vec![128; WIDTH * FIELD_HEIGHT * 3];
    let out = Engine::new(p)
        .unwrap()
        .render_field(&input, 1, 0, true)
        .unwrap();
    assert_eq!(out.taps["comp_in"].len(), 312 * 1135);
    assert!(!out.taps.contains_key("fm"));
    let mid = (140 * WIDTH + 360) * 3;
    for c in 0..3 {
        assert!(
            (out.rgb[mid + c] as i32 - 128).abs() < 18,
            "{:?}",
            &out.rgb[mid..mid + 3]
        );
    }
}

#[test]
fn scipy_filter_and_polyphase_reference_fixtures() {
    let fs = 17_734_375.0;
    let mut x = vec![0.0; 64];
    x[8..24].fill(0.7);
    x[24..].fill(-0.3);
    let cases = [
        (
            dsp::lowpass(1e6, 4, fs),
            [
                0.0004512885787144252,
                0.003644797563331522,
                0.08168542289382028,
                0.7077171502933687,
                0.7599828746965656,
                0.37380082982968243,
                -0.4041659649041619,
                -0.30135058101847706,
            ],
        ),
        (
            dsp::highpass(1.4e6, 2, fs),
            [
                0.49218640207443104,
                0.15556958233503565,
                -0.15055249496572037,
                0.007107583616684232,
                -0.2208442714042936,
                0.14471683329382287,
                -0.0038261714360954824,
                1.2047193069519846e-6,
            ],
        ),
        (
            dsp::bandpass(4_433_618.75 - 1.4e6, 4_433_618.75 + 1.4e6, 2, fs),
            [
                0.09959591229782079,
                0.09959321693764465,
                0.08995357200299144,
                -0.005499756089276159,
                -0.1413853362772673,
                0.026759590055970284,
                -0.0012671900437747994,
                -2.969322596903132e-7,
            ],
        ),
        (
            dsp::notch(4_433_618.75, 2.5, fs),
            [
                0.5283331263431271,
                0.5283354215946531,
                0.6554305528246781,
                0.6969957315259333,
                -0.05554462125315143,
                -0.332339335245255,
                -0.29888927140764016,
                -0.3000006671213269,
            ],
        ),
        (
            dsp::shelf(0.7e6, 9.0, fs, false),
            [
                1.643223086482605,
                1.1546748174771508,
                0.7509284358798387,
                0.7001484746023034,
                -0.9495315891166087,
                -0.3169056811039213,
                -0.30001145242517574,
                -0.3000000000005886,
            ],
        ),
        (
            dsp::peak(5e6, 3.0, 1.2, fs),
            [
                0.7738403674941934,
                0.7519302577556155,
                0.7281521234175539,
                0.6998382435302286,
                -0.37429054723558486,
                -0.28176480339286675,
                -0.29955136787767905,
                -0.3000001334570326,
            ],
        ),
    ];
    for (f, want) in cases {
        let got = f.run(&x);
        for (index, want) in [8, 9, 12, 20, 25, 30, 40, 63].into_iter().zip(want) {
            assert!(
                (got[index] - want).abs() < 1e-10,
                "index {index}: {} != {want}",
                got[index]
            );
        }
    }
    let got = dsp::upsample2(&[0.0, 1.0, 0.0, -0.5, 0.0, 0.0]);
    let want = [
        0.0,
        0.5781124074487445,
        1.0005174705960602,
        0.7343308887583354,
        0.0,
        -0.5185607404757685,
        -0.5002587352980301,
        -0.2061237778565867,
        0.0,
        0.03224983763424402,
        0.0,
        -0.011242042763707792,
    ];
    for (a, b) in got.iter().zip(want) {
        assert!((a - b).abs() < 1e-12, "{a} != {b}");
    }
}

#[test]
fn noiseless_pal_vhs_matches_reference_colour_bars() {
    let mut p = Params::default();
    for key in [
        "tape_noise",
        "chroma_noise",
        "tb_jitter_ns",
        "tb_wobble_ns",
        "tb_skew_us",
        "hs_phase_deg",
        "hs_shift_us",
        "hs_noise",
        "dropout_rate",
        "out_noise",
    ] {
        p.set(key, json!(0)).unwrap();
    }
    p.set("hs_model", json!("off")).unwrap();
    p.set("rf_rate", json!("1x")).unwrap();
    let colors = [
        [255, 255, 255],
        [255, 255, 0],
        [0, 255, 255],
        [0, 255, 0],
        [255, 0, 255],
        [255, 0, 0],
        [0, 0, 255],
        [0, 0, 0],
    ];
    let mut rgb = Vec::new();
    for _ in 0..FIELD_HEIGHT {
        for x in 0..WIDTH {
            rgb.extend_from_slice(&colors[x / 90]);
        }
    }
    let out = Engine::new(p)
        .unwrap()
        .render_field(&rgb, 0, 0, true)
        .unwrap();
    let expected = [
        [228, 228, 228],
        [223, 219, 5],
        [0, 246, 214],
        [0, 237, 0],
        [216, 5, 255],
        [211, 34, 0],
        [0, 0, 255],
        [0, 0, 0],
    ];
    for (bar, want) in expected.iter().enumerate() {
        let i = (140 * WIDTH + bar * 90 + 45) * 3;
        for c in 0..3 {
            assert!(
                (out.rgb[i + c] as i32 - want[c]).abs() <= 2,
                "bar {bar}: {:?} != {want:?}",
                &out.rgb[i..i + 3]
            );
        }
    }
    let expected = [
        (
            "comp_in",
            [
                0.6999999904290531,
                0.6069777660869418,
                0.39982565612408677,
                0.34891846433521106,
                0.04784263064561593,
                0.6520181454534086,
                0.349739679105166,
                0.30258285292945736,
                -0.013767325230304025,
                -3.458608357548443e-10,
            ],
        ),
        (
            "rec_luma",
            [
                0.7023836839847932,
                0.7387005685629708,
                0.6164096219895545,
                0.4907856560025836,
                0.4109166727798381,
                0.28906747211372585,
                0.20935050156045149,
                0.08059727926263036,
                0.027961768115151345,
                1.1058666493147555e-9,
            ],
        ),
        (
            "c_under",
            [
                0.01234979469966103,
                4.772765524386513e-5,
                -0.06163530313493811,
                -0.4405451976748864,
                0.24763649775382718,
                0.16930521484468955,
                -0.35818480620595583,
                -0.3212851731230419,
                0.1949693550435162,
                6.55181357972848e-10,
            ],
        ),
        (
            "luma_demod",
            [
                0.7181179986989796,
                0.699086123062615,
                0.5958258244163428,
                0.46607926774449826,
                0.3975789972096839,
                0.25694726367677584,
                0.15977497096254337,
                0.1604374809811716,
                0.022118021226153757,
                2.137811141695331e-6,
            ],
        ),
        (
            "c_out",
            [
                -0.036213100346072495,
                -0.002849841810309733,
                -0.02964429437467383,
                -0.10664555162507573,
                -0.09590996904018084,
                0.07650809085252475,
                -0.08741557454087698,
                0.2550791354544435,
                0.15264362204749918,
                0.00022639290338201618,
            ],
        ),
    ];
    for (tap, want) in expected {
        for (i, want) in want.into_iter().enumerate() {
            let got = out.taps[tap][100 * 1135 + 200 + i * 100];
            assert!(
                (got - want).abs() < 0.005,
                "{tap} sample {i}: {got} != {want}"
            );
        }
    }
}

#[test]
fn oversampled_damaged_bottom_field_remains_finite() {
    let mut p = Params::default();
    for (key, val) in [
        ("tracking", -0.8),
        ("track_band", 0.7),
        ("wrinkle", 0.6),
        ("snow_sparse", 0.8),
        ("hs_residual", 0.8),
        ("cu_glitch", 0.8),
        ("chroma_band", 0.8),
        ("wr_count", 3.0),
        ("wr_period", 20.0),
        ("wr_hold", 80.0),
    ] {
        p.set(key, json!(val)).unwrap();
    }
    p.set("wr_travel", json!(true)).unwrap();
    p.set("wr_style", json!("grey fade")).unwrap();
    let rgb: Vec<_> = (0..WIDTH * FIELD_HEIGHT * 3)
        .map(|i| ((i / 3) % WIDTH * 255 / WIDTH) as u8)
        .collect();
    let out = Engine::new(p)
        .unwrap()
        .render_field(&rgb, 1, 48, true)
        .unwrap();
    assert_eq!(out.taps["fm"].len(), 2 * 312 * 1135);
    assert!(out.taps.values().flatten().all(|v| v.is_finite()));
    assert!(out.rgb.iter().any(|v| *v > 100));
}

#[test]
fn whole_fields_match_python_colour_bar_fixtures() {
    let reference: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/signal_reference.json")).unwrap();
    let colors = [
        [255, 255, 255],
        [255, 255, 0],
        [0, 255, 255],
        [0, 255, 0],
        [255, 0, 255],
        [255, 0, 0],
        [0, 0, 255],
        [0, 0, 0],
    ];
    let rgb: Vec<u8> = (0..FIELD_HEIGHT * WIDTH)
        .flat_map(|i| colors[(i % WIDTH) / 90])
        .collect();
    for rate in ["1x", "2x"] {
        let mut p = Params::default();
        for key in [
            "tape_noise",
            "chroma_noise",
            "tb_jitter_ns",
            "tb_wobble_ns",
            "tb_skew_us",
            "hs_phase_deg",
            "hs_shift_us",
            "hs_noise",
            "dropout_rate",
            "out_noise",
        ] {
            p.set(key, json!(0)).unwrap();
        }
        p.set("hs_model", json!("off")).unwrap();
        p.set("rf_rate", json!(rate)).unwrap();
        let mut engine = Engine::new(p).unwrap();
        for fi in 0..2 {
            let name = format!("bars_{rate}_field{fi}");
            let path = format!("{}/tests/fixtures/{name}.rgb", env!("CARGO_MANIFEST_DIR"));
            let expected = std::fs::read(path).unwrap();
            let actual = engine.render_field(&rgb, fi, 0, true).unwrap();
            assert_eq!(actual.rgb.len(), expected.len());
            let errors: Vec<_> = actual
                .rgb
                .iter()
                .zip(&expected)
                .map(|(a, b)| a.abs_diff(*b) as f64)
                .collect();
            let max = errors.iter().copied().fold(0.0, f64::max);
            let mae = errors.iter().sum::<f64>() / errors.len() as f64;
            let rms = (errors.iter().map(|e| e * e).sum::<f64>() / errors.len() as f64).sqrt();
            let over_one = errors.iter().filter(|e| **e > 1.0).count();
            eprintln!(
                "{name}: RGB max={max}, MAE={mae:.6}, RMS={rms:.6}, channels >1={over_one}/{}",
                errors.len()
            );
            for (tap, fixture) in reference["cases"][&name]["taps"].as_object().unwrap() {
                let Some(got) = actual.taps.get(tap) else {
                    continue;
                };
                assert_eq!(got.len() as u64, fixture["length"].as_u64().unwrap());
                let stride = fixture["stride"].as_u64().unwrap() as usize;
                let pairs: Vec<_> = got
                    .iter()
                    .step_by(stride)
                    .zip(fixture["values"].as_array().unwrap())
                    .map(|(a, b)| (*a, b.as_f64().unwrap()))
                    .collect();
                let err = pairs.iter().map(|(a, b)| (a - b).powi(2)).sum::<f64>();
                let power = pairs.iter().map(|(_, b)| b * b).sum::<f64>();
                let relative = (err / power.max(1e-30)).sqrt();
                eprintln!("  {tap}: sampled relative RMS={relative:.8}");
            }
            assert!(max <= 1.0, "{name} max channel error {max}");
        }
    }
}
