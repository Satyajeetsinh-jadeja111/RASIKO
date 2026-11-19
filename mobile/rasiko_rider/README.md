# Rasiko Rider — Android and iPhone project

Flutter app for invited seller riders: secure token storage, invitation registration, online/offline availability, consented location updates, delivery offers and sound, atomic acceptance, pickup, map/call handoff, delivery OTP, COD display and history. Navigation supports English, Hindi and Gujarati. No Firebase or server credentials are bundled.

## Verified here

A temporary official Flutter **3.29.3 / Dart 3.7** toolchain resolved dependencies (recorded in `pubspec.lock`). `flutter analyze --no-pub` passed, and two widget tests passed for invitation login, Hindi and a 320px Gujarati screen. Android/iOS project files, platform permission declarations, Rasiko icons, custom sound resources and iOS 13 minimum deployment target are included.

**Android debug APK built successfully on 2026-10-24** using the project-local low-resource profile: 1536 MB Gradle heap, two workers, parallel execution disabled, Kotlin in-process and reduced CPU/disk priority. Gradle completed in 2m 20s. The original build was not interrupted; it ended with a missing Ninja tool error, then a single sequential retry succeeded after local CMake/Ninja installation. Output: `artifacts/rasiko-rider-debug.apk` at the repository root (about 190 MB). This is a development build for `https://rasiko.in`, with Firebase push disabled.

No IPA, release signing, store distribution or physical-device test is verified. iOS compilation/signing needs macOS/Xcode and your development team. The provisional application/bundle ID remains `in.rasiko.rasiko_rider`; confirm ownership before publishing. The native log recommends NDK 27 for some plugin declarations; this debug build passed with installed NDK 26.3.11579264. Review that alignment before release toolchain upgrades.

## Configure and build

1. Install a compatible stable Flutter/Dart toolchain, JDK 17+ and Android SDK. On macOS install Xcode and CocoaPods for iOS. Run `flutter pub get` from this directory. Do not regenerate the existing native project over the configured files.
2. Register Android/iOS applications in your Firebase project. Add `android/app/google-services.json` and `ios/Runner/GoogleService-Info.plist` locally using [Firebase's Flutter setup](https://firebase.google.com/docs/flutter/setup). Configure Android Google Services and iOS APNs credentials, Push Notifications capability and signing entitlements in Xcode. Owner-provided Firebase/signing files are ignored by Git.
3. Notification channel `delivery_offers` uses the included `delivery_offer.wav` resource. Android notification permission and iOS authorization are requested after login when push is enabled. Permission, silent/DND, volume and battery restrictions remain under device/user control; no critical-alert or full-screen-call entitlement is assumed.
4. Run `flutter analyze`, `flutter test --dart-define=RASIKO_API_URL=https://your-server.example`, then `flutter run --dart-define=RASIKO_API_URL=https://your-server.example --dart-define=RASIKO_PUSH_ENABLED=true`. The URL must be an HTTPS origin without a trailing slash.
5. Configure an owner-controlled Android release keystore; the project deliberately does not fall back to debug signing for release. Build `flutter build appbundle` and, on macOS, `flutter build ipa`, supplying the same defines and your signing setup. Verify push entitlements, bundle IDs and provisioning before distribution.

## Availability and location

Foreground heartbeats run every 30 seconds. With location consent enabled, the app also starts a position stream: Android uses Geolocator's visible foreground location notification/wake lock; iOS uses background location mode with an indicator and the configured usage explanations. Going offline, logging out or disposing the app stops that stream.

These platform paths are implemented in source but **not field-verified**. Users must grant the required location permissions; iOS may require Always permission for background updates. If background location is denied/unavailable, keep the app open while online. The backend marks stopped heartbeats stale after 90 seconds; it does not pretend a killed/background-restricted app is available. Force-stop behavior, stationary background tracking, battery management and permission changes require real devices before dispatch launch.

## Registration and field checks

Seller/Head/admin creates an invitation in `/partners/`. New riders enter the invited email, a strong password and code, then choose Register with invitation. Existing customer accounts use Sign in with their password and invitation. No arbitrary seller identifier can register a rider. Invitations expire after 48 hours.

Use two devices to accept the same offer simultaneously. Verify exactly one assignment, lost-offer recovery, locked/background/terminated behavior, notification denial, silent/DND behavior, expired offers, stale presence, OTP throttling, lost connectivity, secure logout and COD receipt. Complete seller pickup/customer delivery scenarios and verify online/offline records against the server. Do not claim reliable background availability or notification delivery until these checks pass.

References: [Firebase Flutter setup](https://firebase.google.com/docs/flutter/setup), [FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send/v1-api), [Apple notification authorization](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications).


## Reproducible local Android test build

The workspace helper `../../scripts/build_rider_android.sh` uses preinstalled Flutter 3.29.3, JDK17 and Android SDK from the sibling `.rasiko-tools/` directory (override with `RASIKO_BUILD_TOOLS`). It runs analysis, widget tests and a debug APK build; output goes to the ignored `artifacts/rasiko-rider-debug.apk`. `RASIKO_API_URL` defaults to `https://rasiko.in`; set it to the HTTPS staging origin when testing a pilot. The backend must be deployed and configured there before login/dispatch can work. This helper does not deploy or enable marketplace settings.

Push is disabled in this build until Firebase/APNs setup is supplied. Keep the app open while online to test foreground polling, sound, acceptance, pickup, buyer OTP and COD. Install the APK only as a development build on your Android phone; it is not a signed Play Store release. Test iPhone behavior separately using a Mac/Xcode build and your friend's iPhone. A debug APK build alone cannot verify background notifications or location reliability.


## Resource limits on the Ubuntu development laptop

Project-local `android/gradle.properties` limits Gradle to two workers, disables parallel builds and exposes two processors to the Gradle JVM and caps its heap at 1536 MB, metaspace at 512 MB and code cache at 128 MB. Project-local task caching avoids unnecessary repeat compilation. Kotlin compiles inside that bounded Gradle JVM; future Gradle invocations do not keep an idle daemon after completion. These settings apply to subsequent invocations. The build already running when the settings were changed was not stopped, restarted, reprioritized or resized.

The Ubuntu helper takes a project-local nonblocking lock and refuses another invocation while a RASIKO Flutter/Gradle process is running. Its pub, analysis, test and APK steps run sequentially with reduced CPU and disk priority; Flutter tests use one worker. No global Gradle, Java, OS or other-project settings are changed. A full debug APK build passed with this profile after the earlier build ended naturally. If a future build reports a heap/metaspace error, diagnose that specific failure before changing the limits. Avoid simultaneous Android/iOS native builds; the JVM/Gradle limits apply to Android, while iOS build/signing still runs on macOS/Xcode.

The native build also needs Ninja. Android SDK package `cmake;3.22.1` supplies CMake and Ninja; the helper uses that local SDK directory when installed and checks Ninja before starting validation/build steps.


Registration troubleshooting: an HTML/FormatException indicates the configured server did not return the Rider JSON API. On 2026-10-24, the deployed rasiko.in rider login path returned HTML 404 while the local server returned JSON. Deploy/configure the Rider backend at the APK's origin or use a dedicated local development connection/build. Invitations/accounts belong to the server that created them. The client source now gives a safe setup error for malformed/non-object responses; the earlier APK does not yet contain this change. New riders must use Register with invitation, not Sign in.


## USB-local Samsung/Android test

Enable Developer options and USB debugging on the phone, use a USB data cable, unlock it and accept this laptop's debugging authorization. `adb devices` must show exactly the intended phone as `device`, not `unauthorized`. With the local Django server on 127.0.0.1:8001, run `adb reverse tcp:8001 tcp:8001` and install `artifacts/rasiko-rider-usb-debug.apk` with `adb install -r`. Keep the cable connected and the laptop/server running. Reconnect the reverse mapping after a phone reconnect/reboot if needed. No LAN binding or public tunnel is needed.

Build that separate artifact with `RASIKO_USB_LOCAL_TEST=true RASIKO_API_URL=http://127.0.0.1:8001 scripts/build_rider_android.sh` from the repository root. HTTP is accepted only for that exact loopback address with explicit opt-in in a debug build. Android debug-only network security permits loopback cleartext; release configuration is unchanged and requires HTTPS. The default HTTPS APK artifact is preserved. Use an invitation from this local server, and select Register with invitation for a new rider. Enter passwords and invitation codes privately on the phone.

The local marketplace feature switch was enabled for user-requested registration testing on 2026-10-24 and audited; automatic dispatch, payouts and translation switches were not enabled. A local test account does not appear on rasiko.in.

USB-local debug APK built successfully on 2026-10-24 in 113.9 seconds; signature verified. Artifact: artifacts/rasiko-rider-usb-debug.apk (~208 MiB). Six tests and analysis passed. Physical installation and registration await USB data detection; enabling debugging alone did not make the phone appear in ADB/lsusb on this laptop.

A follow-up fixes a client regression rejecting valid offers/delivery-history arrays after successful registration. The response guard accepts JSON maps and lists, rejects scalar/HTML responses, and retains safe API error handling. Update the APK in place; do not uninstall or register again if the account has already been created.
