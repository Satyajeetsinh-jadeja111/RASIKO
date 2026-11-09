import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:audioplayers/audioplayers.dart';

const server = String.fromEnvironment('RASIKO_API_URL');
const usbLocalTest = bool.fromEnvironment('RASIKO_USB_LOCAL_TEST');
const pushEnabled = bool.fromEnvironment('RASIKO_PUSH_ENABLED');
const storage = FlutterSecureStorage();
final alerts = FlutterLocalNotificationsPlugin();

@pragma('vm:entry-point')
Future<void> backgroundMessage(RemoteMessage message) async {
  await Firebase.initializeApp();
  // OS notification payload supplies the background sound. The app revalidates on open.
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!validServerOrigin(server, allowUsb: kDebugMode && usbLocalTest)) {
    runApp(const MaterialApp(
        home: Scaffold(
            body: Center(
                child: Text(
                    'Configure the HTTPS Rider server, or an explicitly enabled USB debug build.')))));
    return;
  }
  await alerts.initialize(const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false)));
  const channel = AndroidNotificationChannel(
      'delivery_offers', 'Delivery offers',
      description: 'Time-sensitive delivery offers',
      importance: Importance.max,
      sound: RawResourceAndroidNotificationSound('delivery_offer'),
      playSound: true);
  await alerts
      .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>()
      ?.createNotificationChannel(channel);
  if (pushEnabled) {
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(backgroundMessage);
  }
  runApp(const RiderApp());
}

bool validServerOrigin(String value, {bool allowUsb = false}) {
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    return false;
  }
  return uri.scheme == 'https' ||
      (allowUsb && value == 'http://127.0.0.1:8001');
}

class Api {
  Api({http.Client? client, String? baseUrl})
      : client = client ?? http.Client(),
        baseUrl = baseUrl ?? server;

  final http.Client client;
  final String baseUrl;
  String? token;
  Future<dynamic> call(String path, [Map<String, dynamic>? data]) async {
    final uri = Uri.parse('$baseUrl/api/v1/rider/$path');
    final headers = {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token'
    };
    final response = await (data == null
            ? client.get(uri, headers: headers)
            : client.post(uri, headers: headers, body: jsonEncode(data)))
        .timeout(const Duration(seconds: 15));
    dynamic body;
    try {
      body = jsonDecode(response.body);
    } on FormatException {
      throw Exception(
          'Rider service unavailable at ${uri.host} (HTTP ${response.statusCode}). '
          'The server returned a web page instead of an API response. '
          'Ask your seller or admin to check the Rider server setup.');
    }
    if (body is! Map && body is! List) {
      throw Exception(
          'Invalid Rider service response. Please contact your seller or admin.');
    }
    if (response.statusCode >= 400) {
      throw Exception(body is Map
          ? body['error'] ?? body['detail'] ?? 'Request failed'
          : 'Request failed');
    }
    return body;
  }
}

const words = <String, List<String>>{
  'title': ['Rasiko Rider', 'रासिको राइडर', 'રાસિકો રાઇડર'],
  'register': [
    'Register with invitation',
    'आमंत्रण से पंजीकरण करें',
    'આમંત્રણથી નોંધણી કરો'
  ],
  'cancel': ['Cancel', 'रद्द करें', 'રદ કરો'],
  'locationDenied': [
    'Location permission is required to share your location.',
    'स्थान साझा करने के लिए अनुमति आवश्यक है।',
    'સ્થાન શેર કરવા પરવાનગી જરૂરી છે.'
  ],
  'connectionError': [
    'Location update failed. Check your connection and availability.',
    'स्थान अपडेट नहीं हुआ। कनेक्शन और उपलब्धता जाँचें।',
    'સ્થાન અપડેટ થયું નથી. કનેક્શન અને ઉપલબ્ધતા તપાસો.'
  ],
  'backgroundError': [
    'Background location is unavailable. Keep the app open or check permissions.',
    'पृष्ठभूमि में स्थान उपलब्ध नहीं है। ऐप खुला रखें या अनुमतियाँ जाँचें।',
    'પૃષ્ઠભૂમિમાં સ્થાન ઉપલબ્ધ નથી. એપ ખુલ્લી રાખો અથવા પરવાનગી તપાસો.'
  ],
  'email': ['Email', 'ईमेल', 'ઈમેલ'],
  'password': ['Password', 'पासवर्ड', 'પાસવર્ડ'],
  'invite': [
    'Invitation code (first login)',
    'आमंत्रण कोड (पहला लॉगिन)',
    'આમંત્રણ કોડ (પ્રથમ લૉગિન)'
  ],
  'login': ['Sign in', 'साइन इन', 'સાઇન ઇન'],
  'online': ['Online', 'ऑनलाइन', 'ઓનલાઇન'],
  'offline': ['Offline', 'ऑफलाइन', 'ઓફલાઇન'],
  'offers': ['Available deliveries', 'उपलब्ध डिलीवरी', 'ઉપલબ્ધ ડિલિવરી'],
  'deliveries': ['Your deliveries', 'आपकी डिलीवरी', 'તમારી ડિલિવરી'],
  'accept': ['Accept delivery', 'डिलीवरी स्वीकार करें', 'ડિલિવરી સ્વીકારો'],
  'pickup': ['Confirm pickup', 'पिकअप की पुष्टि करें', 'પિકઅપની પુષ્ટિ કરો'],
  'deliver': [
    'Confirm delivery',
    'डिलीवरी की पुष्टि करें',
    'ડિલિવરીની પુષ્ટિ કરો'
  ],
  'code': [
    'Customer delivery code',
    'ग्राहक डिलीवरी कोड',
    'ગ્રાહક ડિલિવરી કોડ'
  ],
  'logout': ['Sign out', 'साइन आउट', 'સાઇન આઉટ'],
  'empty': [
    'No deliveries right now.',
    'अभी कोई डिलीवरी नहीं है।',
    'હાલ કોઈ ડિલિવરી નથી.'
  ],
  'location': [
    'Share location while online',
    'ऑनलाइन होने पर स्थान साझा करें',
    'ઓનલાઇન હોય ત્યારે સ્થાન શેર કરો'
  ],
  'cash': ['Collect cash', 'नकद लें', 'રોકડ લો'],
  'navigation': ['Navigate', 'दिशा देखें', 'દિશા જુઓ'],
  'call': ['Call customer', 'ग्राहक को कॉल करें', 'ગ્રાહકને કૉલ કરો'],
};

class RiderApp extends StatefulWidget {
  const RiderApp({super.key});
  @override
  State<RiderApp> createState() => _RiderState();
}

class _RiderState extends State<RiderApp> with WidgetsBindingObserver {
  final navigator = GlobalKey<NavigatorState>();
  final api = Api();
  final email = TextEditingController(),
      password = TextEditingController(),
      invite = TextEditingController();
  AudioPlayer? _audio;
  AudioPlayer get audio => _audio ??= AudioPlayer();
  int language = 0;
  bool online = false, consent = false, busy = false, refreshing = false;
  String? error;
  List<dynamic> offers = [], deliveries = [];
  Set<int> seen = {};
  Timer? poll;
  StreamSubscription<RemoteMessage>? foregroundPush, openedPush;
  StreamSubscription<String>? tokenRefresh;
  StreamSubscription<Position>? locationUpdates;
  String t(String key) => words[key]![language];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    restore();
    if (pushEnabled) {
      foregroundPush = FirebaseMessaging.onMessage.listen((_) => refresh());
      openedPush =
          FirebaseMessaging.onMessageOpenedApp.listen((_) => refresh());
      tokenRefresh =
          FirebaseMessaging.instance.onTokenRefresh.listen((token) async {
        if (api.token != null) {
          try {
            await api.call('device/', {
              'token': token,
              'platform': Platform.isIOS ? 'ios' : 'android'
            });
          } catch (_) {}
        }
      });
    }
  }

  @override
  void dispose() {
    poll?.cancel();
    foregroundPush?.cancel();
    openedPush?.cancel();
    tokenRefresh?.cancel();
    locationUpdates?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _audio?.dispose();
    email.dispose();
    password.dispose();
    invite.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && api.token != null) refresh();
    if (state == AppLifecycleState.paused) audio.stop();
  }

  Future<void> restore() async {
    api.token = await storage.read(key: 'rider_token');
    if (!mounted) return;
    setState(() {});
    if (api.token != null) {
      startPolling();
      await refresh();
    }
  }

  void startPolling() {
    poll?.cancel();
    poll = Timer.periodic(const Duration(seconds: 30), (_) => refresh());
  }

  Future<void> guard(Future<void> Function() action) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> login({bool register = false}) => guard(() async {
        final body = await api.call(register ? 'register/' : 'login/', {
          'email': email.text.trim(),
          'password': password.text,
          if (invite.text.isNotEmpty) 'invitation': invite.text.trim()
        });
        api.token = body['token'];
        await storage.write(key: 'rider_token', value: api.token);
        password.clear();
        invite.clear();
        if (pushEnabled) {
          await FirebaseMessaging.instance
              .requestPermission(alert: true, sound: true, badge: true);
          final token = await FirebaseMessaging.instance.getToken();
          if (token != null) {
            await api.call('device/', {
              'token': token,
              'platform': Platform.isIOS ? 'ios' : 'android'
            });
          }
        }
        startPolling();
        await refresh();
      });
  Future<void> refresh() async {
    if (api.token == null || refreshing) return;
    refreshing = true;
    try {
      Position? position;
      if (online && consent) {
        position = await Geolocator.getCurrentPosition(
            locationSettings: const LocationSettings(
                accuracy: LocationAccuracy.high,
                timeLimit: Duration(seconds: 10)));
      }
      await api.call('heartbeat/', {
        'online': online,
        'consent': consent,
        if (position != null) 'lat': position.latitude,
        if (position != null) 'lng': position.longitude
      });
      final next = await api.call('offers/') as List<dynamic>;
      final trips = await api.call('deliveries/') as List<dynamic>;
      final ids = next.map((o) => o['id'] as int).toSet();
      if (online && ids.difference(seen).isNotEmpty) {
        await HapticFeedback.heavyImpact();
        await audio.play(AssetSource('delivery_offer.wav'));
      }
      seen = ids;
      if (next.isEmpty) await audio.stop();
      if (mounted) {
        setState(() {
          offers = next;
          deliveries = trips;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      refreshing = false;
    }
  }

  Future<void> toggleOnline(bool value) => guard(() async {
        if (value && consent) {
          var permission = await Geolocator.checkPermission();
          if (permission == LocationPermission.denied) {
            permission = await Geolocator.requestPermission();
          }
          if (permission == LocationPermission.denied ||
              permission == LocationPermission.deniedForever) {
            throw Exception(t('locationDenied'));
          }
        }
        await api.call('heartbeat/', {'online': value, 'consent': consent});
        online = value;
        await locationUpdates?.cancel();
        locationUpdates = null;
        if (value && consent) {
          final LocationSettings locationSettings = Platform.isAndroid
              ? AndroidSettings(
                  accuracy: LocationAccuracy.high,
                  distanceFilter: 0,
                  intervalDuration: const Duration(seconds: 30),
                  foregroundNotificationConfig: const ForegroundNotificationConfig(
                      notificationTitle: 'Rasiko Rider online',
                      notificationText:
                          'Sharing delivery availability and location with your seller.',
                      enableWakeLock: true))
              : AppleSettings(
                  accuracy: LocationAccuracy.high,
                  activityType: ActivityType.automotiveNavigation,
                  distanceFilter: 0,
                  pauseLocationUpdatesAutomatically: false,
                  showBackgroundLocationIndicator: true,
                  allowBackgroundLocationUpdates: true);
          locationUpdates =
              Geolocator.getPositionStream(locationSettings: locationSettings)
                  .listen((position) async {
            if (!online || api.token == null) return;
            try {
              await api.call('heartbeat/', {
                'online': true,
                'consent': true,
                'lat': position.latitude,
                'lng': position.longitude
              });
            } catch (_) {
              if (mounted) setState(() => error = t('connectionError'));
            }
          }, onError: (_) {
            if (mounted) setState(() => error = t('backgroundError'));
          });
        }
        await refresh();
      });
  Future<void> accept(int id) => guard(() async {
        await api.call('offers/$id/accept/', {});
        await audio.stop();
        await refresh();
      });
  Future<void> deliver(Map<String, dynamic> trip) async {
    final controller = TextEditingController();
    final code = await showDialog<String>(
        context: navigator.currentContext!,
        builder: (ctx) => AlertDialog(
                title: Text(t('code')),
                content: TextField(
                    controller: controller,
                    keyboardType: TextInputType.number,
                    maxLength: 6),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: Text(t('cancel'))),
                  FilledButton(
                      onPressed: () => Navigator.pop(ctx, controller.text),
                      child: Text(t('deliver')))
                ]));
    controller.dispose();
    if (code != null) {
      await guard(() async {
        await api.call('deliveries/${trip['id']}/deliver/', {'otp': code});
        await refresh();
      });
    }
  }

  Future<void> logout() => guard(() async {
        await api.call('logout/', {});
        await locationUpdates?.cancel();
        locationUpdates = null;
        await storage.delete(key: 'rider_token');
        api.token = null;
        online = false;
        offers = [];
        deliveries = [];
        poll?.cancel();
        await audio.stop();
      });
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
        navigatorKey: navigator,
        debugShowCheckedModeBanner: false,
        title: t('title'),
        theme: ThemeData(
            colorScheme:
                ColorScheme.fromSeed(seedColor: const Color(0xff245843)),
            scaffoldBackgroundColor: const Color(0xfffbf8f1),
            useMaterial3: true),
        home: Scaffold(
            appBar: AppBar(title: Text(t('title')), actions: [
              DropdownButton<int>(
                  value: language,
                  items: const [
                    DropdownMenuItem(value: 0, child: Text('English')),
                    DropdownMenuItem(value: 1, child: Text('हिन्दी')),
                    DropdownMenuItem(value: 2, child: Text('ગુજરાતી'))
                  ],
                  onChanged: (v) => setState(() => language = v ?? 0))
            ]),
            body: SafeArea(
                child: RefreshIndicator(
                    onRefresh: refresh,
                    child:
                        ListView(padding: const EdgeInsets.all(20), children: [
                      if (error != null)
                        Card(
                            color: Colors.red.shade50,
                            child: Padding(
                                padding: const EdgeInsets.all(16),
                                child: Text(error!, semanticsLabel: error))),
                      if (busy) const LinearProgressIndicator(),
                      if (api.token == null) ...[
                        TextField(
                            controller: email,
                            keyboardType: TextInputType.emailAddress,
                            decoration: InputDecoration(labelText: t('email'))),
                        TextField(
                            controller: password,
                            obscureText: true,
                            decoration:
                                InputDecoration(labelText: t('password'))),
                        TextField(
                            controller: invite,
                            decoration:
                                InputDecoration(labelText: t('invite'))),
                        const SizedBox(height: 24),
                        FilledButton(
                            onPressed: busy ? null : () => login(),
                            child: Text(t('login'))),
                        TextButton(
                            onPressed:
                                busy ? null : () => login(register: true),
                            child: Text(t('register'))),
                      ] else ...[
                        SwitchListTile(
                            title: Text(online ? t('online') : t('offline')),
                            value: online,
                            onChanged: busy ? null : toggleOnline),
                        SwitchListTile(
                            title: Text(t('location')),
                            value: consent,
                            onChanged: online
                                ? null
                                : (value) => setState(() => consent = value)),
                        Text(t('offers'),
                            style: Theme.of(context).textTheme.headlineSmall),
                        if (offers.isEmpty)
                          Padding(
                              padding: const EdgeInsets.all(20),
                              child: Text(t('empty'))),
                        for (final offer in offers)
                          Card(
                              child: Padding(
                                  padding: const EdgeInsets.all(20),
                                  child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                            '${offer['brand']} · ${offer['area']}'),
                                        Text('${offer['expires_at']}'),
                                        FilledButton(
                                            onPressed: busy || !online
                                                ? null
                                                : () => accept(offer['id']),
                                            child: Text(t('accept')))
                                      ]))),
                        Text(t('deliveries'),
                            style: Theme.of(context).textTheme.headlineSmall),
                        for (final trip in deliveries)
                          Card(
                              child: Padding(
                                  padding: const EdgeInsets.all(20),
                                  child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                            '${trip['brand']} · ${trip['status']}'),
                                        Text('${trip['recipient']}'),
                                        Text('${trip['address']}'),
                                        if (trip['cod'] != '0.00' &&
                                            trip['status'] != 'delivered')
                                          Text('${t('cash')}: ₹${trip['cod']}'),
                                        if (trip['status'] == 'assigned')
                                          FilledButton(
                                              onPressed: busy
                                                  ? null
                                                  : () => guard(() async {
                                                        await api.call(
                                                            'deliveries/${trip['id']}/pickup/',
                                                            {});
                                                        await refresh();
                                                      }),
                                              child: Text(t('pickup'))),
                                        if (trip['status'] == 'picked_up') ...[
                                          TextButton(
                                              onPressed: () => launchUrl(Uri.parse(
                                                  'https://www.google.com/maps/dir/?api=1&destination=${trip['lat']},${trip['lng']}')),
                                              child: Text(t('navigation'))),
                                          TextButton(
                                              onPressed: () => launchUrl(Uri(
                                                  scheme: 'tel',
                                                  path: trip['phone'])),
                                              child: Text(t('call'))),
                                          FilledButton(
                                              onPressed: busy
                                                  ? null
                                                  : () => deliver(
                                                      Map<String, dynamic>.from(
                                                          trip)),
                                              child: Text(t('deliver'))),
                                        ],
                                      ]))),
                        TextButton(
                            onPressed: busy ? null : logout,
                            child: Text(t('logout'))),
                      ],
                    ])))));
  }
}
