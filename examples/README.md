# Try the renderer

Run these commands from the repository root in PowerShell. They use FFmpeg's synthetic test pattern, so you can reproduce the example without downloading any footage. Each export renders the same first frame at 2× RF sampling.

```powershell
New-Item -ItemType Directory -Force test-output | Out-Null
ffmpeg -hide_banner -y -f lavfi -i "testsrc2=size=768x576:rate=25" -t 1 -c:v libx264 -pix_fmt yuv420p test-output/source.mp4

cargo run --release --locked --no-default-features -- test-output/source.mp4 --preset "PAL VHS / SP - home recording" --set field_mode=frame --set rf_rate=2x --export test-output/home.mp4 --max-frames 1 --no-audio

cargo run --release --locked --no-default-features -- test-output/source.mp4 --params examples/rf-snow.json --export test-output/rf-snow.mp4 --max-frames 1 --no-audio
```

Open `test-output/source.mp4` on desktop and load [rf-snow.json](rf-snow.json) from the parameter controls. The demonstration moves the RF switch earlier and enlarges the snow so that you can follow it near the bottom of the image. Go to **Advanced → Head switching** and toggle **Snow follows head-switch line** to compare it with fixed placement. On Android, the same parameters are available in the **Head switching** group.

The main README comparison uses the first source frame and the two rendered outputs from these commands.
