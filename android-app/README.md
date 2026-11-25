# TangLisp Companion (Android) — v0

## v0.6 config-flash burn (2026-11-25)

- **Flash** button (main screen): pick a raw flash image (the
  fs2flash.py output, e.g. soc_flash.bin) and burn it into the
  GW5A's config flash (XTX XT25F64B) via JTAG on FT2232
  channel A — no Termux, no PC. A confirm dialog shows the size
  and MD5 before anything is erased. The console disconnects
  first (the burn owns the USB device), a wake lock is held,
  progress goes to the status line and console, and the button
  becomes **Cancel flash** while running (the flash is left
  incomplete on cancel and must be re-burned).
- Implementation: `FlashWriter.kt` is a step-for-step port of
  the hardware-proven Python burner (flash_write6.py): MPSSE
  transport, the BL616's <<1 IR latch quirk, SPI bridge entry,
  JEDEC gate (0B 40 17), scratch-block erase test, fixed waits
  instead of RDSR polling, full read-back MD5 verify, RELOAD +
  DONE check at the end. The debugger itself is never written.
  One adaptation: `UsbDeviceConnection.resetDevice()` is a
  system API, so it is invoked reflectively with a re-open
  fallback.
- APK: versionCode 6 / versionName 0.6, manual pipeline, dex
  verified (FLASH_WRITE_DONE + STORE-READY present).
  **Not yet run on hardware** — the first burn is the test; the
  Termux path remains the proven fallback, and a failed burn is
  recoverable by simply burning again.

## v0.5 file send (2026-11-25)

- **Send file** button (main screen): pick a file, and the app
  stores it on the board's SD card. The receiving side is NOT in
  the firmware — it is a Lisp driver on the card itself
  (SDW1..SDW6.LSP, written in TangLisp over the SPI prims). The
  app sends `(load SDWn.LSP)` for n=1..6 (waiting for the prompt
  each time), then `(recv-file (quote (<11 name bytes>)) <len>)`,
  waits for the driver's `STORE-READY` line, streams the payload
  in 256-byte chunks paced 25 ms apart, and reports success when
  the result prompt returns. The 8.3 name is derived from the
  picked file's display name (uppercased, sanitized, padded).
  Files over 1,279 bytes are stored as data but cannot be
  `(load)`ed; the hard cap is 65,536 bytes.
- Prerequisite on the board: PROG41 firmware (64 KB RAM) at the
  REPL, with SDW1..6.LSP on the card. Sending while the boot menu
  is up does not work (the keystrokes go to the menu).
- The viewer now knows **IMG_VERSION 12** (PROG41: NCELLS 2560,
  NSYMS 192, cells @ 0x8450, symtab @ 0x6850). v7/v8 stay viewable.
- APK: versionCode 5 / versionName 0.5, built with the manual
  pipeline, dex verified to contain the send flow (STORE-READY).
  Not yet run on a phone.

## v0.4 live world fetch (2026-11-25)

- With the console connected, the **World** button now fetches the
  board's world live: the app sends `(dump)`, the firmware
  (PROG40) answers with a `WORLD-BEGIN <bytes>` line followed by
  the raw heap image in the exact `(save)` format, and the viewer
  opens on it. Incoming serial data is diverted into the capture
  while a fetch is in flight (20 s timeout); everything else still
  reaches the console. Disconnected, the button just opens the
  viewer (file mode) as before.
- The viewer now knows **IMG_VERSION 8** too (PROG40: NCELLS 288,
  cells @ 0x6D20, symtab @ 0x5620). v7 worlds stay viewable.
- Firmware side: prim `(dump)` (index 35) streams the image over
  the UART; `heap_save_to` and the dump share the header/stats/
  block-fill helpers. NCELLS went 320 → 288 so the build keeps
  the ≥ 2.3 KB stack-slack rule (final: 2,363 B). Verified on
  hardware from SRAM: the board streamed its live world
  (x = 42 defined at the REPL seconds earlier, fib/count
  closures, checksum valid).

## v0.3 world viewer (2026-11-25)

- **World button** (main screen) opens the world viewer: pick a
  TangLisp heap image (.BIN written by `(save …)` on the board) with
  the system file picker and the app draws it — a heap grid
  (amber = alive/reachable from the global env, blue-grey = used,
  dark = free), the global bindings list, and a full s-expression
  rendering of any binding (closures shown as lambda forms; their
  env is circular and is not expanded).
- Parser: `WorldImage.kt` mirrors `heap_save_to()` in
  `lisp-sd/lisp_sd.c`. Layout profiles are keyed by IMG_VERSION —
  currently only **v7** (PROG39 firmware: NCELLS 320, NSYMS 80,
  cells @ 0x6C60, symtab @ 0x5560 from that build's fw.elf). A world
  with an unknown version is reported, not misparsed. If the
  firmware layout changes, bump IMG_VERSION and add a profile.
- `tools/make_test_world.py` synthesizes a valid v7 world
  (fib/count closures, x = 42, y = (1 2 3), prim bindings) for
  trying the viewer without a card reader.
- Signed with the same `~/.android/debug.keystore` as v0.2, so
  v0.3 installs over v0.2 in place.
- Manual-pipeline additions: `d8 --output` needs an existing
  directory, and the dex must be zipped into the APK **from inside
  the dex directory** so `classes.dex` lands at the archive root.

## v0.2 design pass (2026-11-25)

- **Launcher icon**: pixel-art PCB + Lisp parens (cream parens and a
  pink dot on a green board with copper traces, a chip and a gold pin
  header), generated by `tools/make_icon.py` into adaptive-icon +
  per-density PNG resources.
- **Evening-room UI**: warm charcoal surfaces, cream text, a rounded
  dark console, amber accents — and the connection state shown as
  **lamplight**: the dot beside the status line glows amber when
  connected and sits blue-grey when not (drawables `lamp_on` /
  `lamp_off`, palette in `res/values/colors.xml`).
- Signed with `~/.android/debug.keystore` (generated 2026-11-25; the
  v0.1 build's keystore did not survive), so **uninstall v0.1 before
  installing v0.2** — Android refuses a signature-changing update.
- Manual-pipeline pitfalls found this round: `~` does not expand
  mid-classpath (use `$HOME`), and `kotlinc`/`d8` need the JDK on
  `PATH` (`export JAVA_HOME=~/workspace/jdk17; PATH=$JAVA_HOME/bin:$PATH`).
  Always verify the dex actually contains `MainActivity` afterwards —
  a failed kotlinc step otherwise still yields a signed, broken APK.


A remote-control console for the TangLisp machine (Tang Primer 25K +
hand-built PicoRV32 SoC running the TangLisp interpreter).

The dock's BL616 debugger enumerates over USB as an FTDI FT2232 clone
(VID `0x0403`, PID `0x6010`, dual serial). Channel B — usb-serial port
index 1 — is the FPGA's UART console at 115200 baud 8N1. Established
hardware fact: **no data flows unless DTR is asserted**, so the app sets
DTR immediately after opening the port.

## What v0 does

- Kotlin, single `Activity`, minSdk 26, no AndroidX UI dependencies.
- USB library: `com.github.mik3y:usb-serial-for-android:3.8.1` (JitPack).
- Finds the FT2232, requests USB permission (also offered automatically
  when the dock is plugged in, via the `USB_DEVICE_ATTACHED` intent
  filter + `res/xml/device_filter.xml`), opens **port index 1** at
  115200 8N1 with **DTR on**.
- UI: connection status line + Connect/Disconnect button, a scrolling
  monospace console (auto-scroll, capped at 32k chars), a text field +
  Send button (sends the text plus `\n`), and a keypad row with digits
  **0–9** and **Enter**. Digits are sent as single bytes with no newline,
  because the on-device boot launcher (PROG38) reads exactly one
  keypress to pick a world/app from its menu; Enter sends `\n` for the
  REPL.
- Clean connect/disconnect: detach broadcast closes the port, serial
  errors disconnect and say so, `onDestroy` releases everything.

Not in v0 (by design): file transfer, virtual dock buttons beyond the
digit pad, WiFi/BLE via the Pocket-Dongle-S3. Those are later phases of
the firmware plan (`../FIRMWARE.md`, F5 / input design).

## Build (normal environment)

```sh
export JAVA_HOME=~/workspace/jdk17            # Temurin 17.0.21.1+2
export ANDROID_HOME=~/workspace/android-sdk
export GRADLE_USER_HOME=~/workspace/.gradle
cd ~/workspace/tang/android-app
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

`local.properties` already points at `sdk.dir=/home/hatch/workspace/android-sdk`.

## Toolchain (all under ~/workspace — the VM is replaceable, /usr is not)

| Piece | Version | Path |
|---|---|---|
| JDK | Temurin 17.0.21.1+2 | `~/workspace/jdk17` → `jdk-17.0.21.1+2/` |
| Gradle | 8.9 | `~/workspace/gradle-8.9/` (wrapper in project pins 8.9) |
| AGP / Kotlin plugin | 8.7.3 / 2.0.21 | resolved by Gradle |
| Kotlin compiler (manual build) | 2.0.21 | `~/workspace/kotlinc/` |
| Android SDK platform | android-34 (rev 3) | `~/workspace/android-sdk/platforms/android-34` |
| Build-tools | 34.0.0 | `~/workspace/android-sdk/build-tools/34.0.0` |
| Platform-tools | 37.0.3 | `~/workspace/android-sdk/platform-tools` |
| usb-serial-for-android | 3.8.1 | JitPack (Gradle) |

The SDK packages were installed by downloading the official zips from
`dl.google.com/android/repository/` with curl and unpacking them into
the layout above; `package.xml` files were written by hand and the
standard SDK license hashes placed in `licenses/`. Once Java networking
is available (see below), re-running
`sdkmanager "platforms;android-34" "build-tools;34.0.0" "platform-tools"`
will normalize everything.

## Sandbox note — why the checked-in APK was built without Gradle

In the subagent sandbox where v0 was scaffolded, **direct TCP from Java
processes is blocked** (Muse Settings → Permissions → Direct network
protocols → `other_tcp` = Deny for that agent). Symptoms, all verified:

- `sdkmanager` dies in `HttpURLConnection.doTunneling0` with
  `NoSuchElementException` (the interceptor answers CONNECT requests
  with a plain-text denial, which the JDK cannot parse).
- `gradle assembleDebug` and even `gradle wrapper` fail with
  **"Could not receive a message from the daemon"** — the Gradle
  client↔daemon loopback connection is intercepted the same way.
  (This is also why `gradle/wrapper/gradle-wrapper.jar` here was taken
  from the Gradle 8.9 distribution's embedded copy and `gradlew` /
  `gradlew.bat` from the gradle/gradle v8.9.0 tag — byte-identical to
  what the wrapper task generates.)

Switching `other_tcp` to **Ask** for the agent (or running the build
from the main agent / any normal shell) unblocks the Gradle build;
`~/workspace/.gradle/gradle.properties` already carries the sandbox
egress-proxy settings Gradle needs for dependency resolution.

The APK shipped here was instead produced with the **manual pipeline**
— the same SDK tools AGP drives — as an end-to-end toolchain proof:

```sh
BT=~/workspace/android-sdk/build-tools/34.0.0
AJ=~/workspace/android-sdk/platforms/android-34/android.jar
# AAR classes: unzip usb-serial-for-android-3.8.1.aar (JitPack) → classes.jar
$BT/aapt2 compile --dir app/src/main/res -o res.zip
$BT/aapt2 link -o app-unsigned.apk -I $AJ --manifest AndroidManifest.xml \
    --java gen --min-sdk-version 26 --target-sdk-version 34 \
    --version-code 1 --version-name 0.1 res.zip
    # (manual link needs package="org.tanglisp.companion" in the manifest;
    #  AGP injects it from the namespace, so a copy was used)
~/workspace/kotlinc/bin/kotlinc \
    -classpath $AJ:classes.jar:androidx-annotation-1.8.0.jar \
    -jvm-target 17 -d classes \
    app/src/main/java/org/tanglisp/companion/MainActivity.kt gen/.../R.java
$BT/d8 --lib $AJ --min-api 26 --output dex \
    app-classes.jar ~/workspace/kotlinc/lib/kotlin-stdlib.jar \
    classes.jar androidx-annotation-1.8.0.jar
zip app-with-dex.apk classes.dex        # into the aapt2 output
$BT/zipalign -p -f 4 app-with-dex.apk app-aligned.apk
$BT/apksigner sign --ks debug.keystore --out app-debug.apk app-aligned.apk
$BT/apksigner verify app-debug.apk      # CN=Android Debug
```

Result: `app/build/outputs/apk/debug/app-debug.apk` (737,852 bytes),
`org.tanglisp.companion` v0.1, minSdk 26 / targetSdk 34, containing
`MainActivity`, the FTDI driver and `SerialInputOutputManager`
(verified in the dex). It has **not** been run on a phone yet — first
on-device check: install, plug the dock in, confirm the boot menu
appears in the console and a digit keypress boots the selected world.

## Layout

```
settings.gradle.kts / build.gradle.kts / gradle.properties
gradle/wrapper/… + gradlew(.bat)     Gradle 8.9 wrapper
app/build.gradle.kts                 AGP 8.7.3, Kotlin 2.0.21, usb-serial dep
app/src/main/AndroidManifest.xml     USB host feature + attach intent
app/src/main/java/org/tanglisp/companion/MainActivity.kt
app/src/main/res/layout/activity_main.xml
app/src/main/res/xml/device_filter.xml   VID 1027 / PID 24592
```
