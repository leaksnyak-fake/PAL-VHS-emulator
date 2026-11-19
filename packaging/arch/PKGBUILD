# Maintainer: leaksnyak-fake
pkgname=pal-vhs
pkgver=1.0.0
pkgrel=1
pkgdesc="PAL VHS degradation emulator"
arch=('x86_64')
url="https://github.com/leaksnyak-fake/PAL-VHS-emulator"
license=('GPL-3.0-or-later')   # change to your actual license
depends=('glib2' 'gstreamer' 'gst-plugins-base' 'gst-plugins-good' 'gst-plugins-bad' 'gst-plugins-ugly' 'gst-libav' 'ffmpeg')
makedepends=('cargo' 'pkgconf')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('793e2e8270f99fab194c7e5cf8eea41cc9bb5dec91f011b9bca75251752405d8')
options=('!debug')

prepare() {
  cd "PAL-VHS-emulator-$pkgver"
  cargo fetch --locked --target "$(rustc -vV | sed -n 's/host: //p')"
}

build() {
  cd "PAL-VHS-emulator-$pkgver"
  cargo build --release --locked
}

package() {
  cd "PAL-VHS-emulator-$pkgver"
  install -Dm755 target/release/pal-vhs "$pkgdir/usr/bin/pal-vhs"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
