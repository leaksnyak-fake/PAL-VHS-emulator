use std::{env, path::PathBuf};

fn main() {
    if env::var_os("CARGO_FEATURE_DESKTOP").is_none()
        || env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows")
    {
        return;
    }
    let filename = if env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc") {
        "pal-vhs.res".into()
    } else {
        format!("pal-vhs-{}.o", env::var("CARGO_CFG_TARGET_ARCH").unwrap())
    };
    let resource = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap())
        .join("assets/icons")
        .join(filename);
    println!("cargo:rerun-if-changed={}", resource.display());
    println!("cargo:rustc-link-arg-bin=pal-vhs={}", resource.display());
}
