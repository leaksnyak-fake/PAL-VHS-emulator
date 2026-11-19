//! JNI bridge for the Android app (Kotlin class `com.palvhs.app.Native`).
use jni::objects::{JByteArray, JClass, JString};
use jni::sys::{jboolean, jbyteArray, jint, jlong, jstring};
use jni::JNIEnv;
use pal_vhs::{mobile::{canvas_to_i420, control_state, i420_to_canvas, preset_names, Session}, model::specs};
use std::panic::{catch_unwind, AssertUnwindSafe};

fn throw(env: &mut JNIEnv, msg: &str) {
    let _ = env.throw_new("java/lang/RuntimeException", msg);
}

/// Run `f`, turning errors and panics into a Java RuntimeException.
fn guarded<T: Default>(env: &mut JNIEnv, f: impl FnOnce(&mut JNIEnv) -> Result<T, String>) -> T {
    match catch_unwind(AssertUnwindSafe(|| f(env))) {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => {
            throw(env, &e);
            T::default()
        }
        Err(_) => {
            throw(env, "Native code panicked");
            T::default()
        }
    }
}

fn jstr(env: &mut JNIEnv, s: &JString) -> Result<String, String> {
    env.get_string(s).map(|s| s.into()).map_err(|e| e.to_string())
}
fn bytes(env: &JNIEnv, a: &JByteArray) -> Result<Vec<u8>, String> {
    env.convert_byte_array(a).map_err(|e| e.to_string())
}
fn out_bytes(env: &JNIEnv, v: &[u8]) -> Result<jbyteArray, String> {
    env.byte_array_from_slice(v).map(|a| a.into_raw()).map_err(|e| e.to_string())
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeCreate<'l>(
    mut env: JNIEnv<'l>,
    _: JClass<'l>,
    preset: JString<'l>,
    overrides: JString<'l>,
) -> jlong {
    guarded(&mut env, |env| {
        let (p, o) = (jstr(env, &preset)?, jstr(env, &overrides)?);
        Ok(Box::into_raw(Box::new(Session::new(&p, &o)?)) as jlong)
    })
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeDestroy<'l>(_: JNIEnv<'l>, _: JClass<'l>, h: jlong) {
    if h != 0 {
        drop(unsafe { Box::from_raw(h as *mut Session) });
    }
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeAspect<'l>(
    mut env: JNIEnv<'l>,
    _: JClass<'l>,
    h: jlong,
) -> jstring {
    guarded(&mut env, |env| {
        let s = unsafe { (h as *const Session).as_ref() }.ok_or("Invalid session")?;
        env.new_string(s.aspect()).map(|s| s.into_raw()).map_err(|e| e.to_string())
    })
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativePresets<'l>(mut env: JNIEnv<'l>, _: JClass<'l>) -> jstring {
    guarded(&mut env, |env| {
        let json = serde_json::to_string(&preset_names()).map_err(|e| e.to_string())?;
        env.new_string(json).map(|s| s.into_raw()).map_err(|e| e.to_string())
    })
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeSchema<'l>(mut env: JNIEnv<'l>, _: JClass<'l>) -> jstring {
    guarded(&mut env, |env| {
        let json = serde_json::to_string(specs()).map_err(|e| e.to_string())?;
        env.new_string(json).map(|s| s.into_raw()).map_err(|e| e.to_string())
    })
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeControlState<'l>(
    mut env: JNIEnv<'l>, _: JClass<'l>, preset: JString<'l>, overrides: JString<'l>,
) -> jstring {
    guarded(&mut env, |env| {
        let (p, o) = (jstr(env, &preset)?, jstr(env, &overrides)?);
        let json = control_state(&p, &o)?.to_string();
        env.new_string(json).map(|s| s.into_raw()).map_err(|e| e.to_string())
    })
}

/// I420 frame of any size -> 720x576 RGB canvas.
#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeFit<'l>(
    mut env: JNIEnv<'l>,
    _: JClass<'l>,
    i420: JByteArray<'l>,
    w: jint,
    h: jint,
    rotation: jint,
    aspect: JString<'l>,
    bt709: jboolean,
) -> jbyteArray {
    guarded(&mut env, |env| {
        let data = bytes(env, &i420)?;
        let aspect = jstr(env, &aspect)?;
        let mut out = vec![0u8; 720 * 576 * 3];
        i420_to_canvas(&data, w as usize, h as usize, rotation as u32, &aspect, bt709 != 0, &mut out)?;
        out_bytes(env, &out)
    })
}

#[no_mangle]
pub extern "system" fn Java_com_palvhs_app_Native_nativeRender<'l>(
    mut env: JNIEnv<'l>,
    _: JClass<'l>,
    h: jlong,
    canvas: JByteArray<'l>,
    second_canvas: JByteArray<'l>,
    frame_idx: jlong,
    for_export: jboolean,
) -> jbyteArray {
    guarded(&mut env, |env| {
        // The Kotlin owner joins export workers before releasing the shared session.
        let s = unsafe { (h as *const Session).as_ref() }.ok_or("Invalid session")?;
        let first = bytes(env, &canvas)?;
        let second = if second_canvas.is_null() { None } else { Some(bytes(env, &second_canvas)?) };
        let rgb = s.render_pair(&first, second.as_deref(), frame_idx as u64, for_export == 0)?;
        if for_export != 0 {
            out_bytes(env, &canvas_to_i420(&rgb)?)
        } else {
            out_bytes(env, &rgb)
        }
    })
}
