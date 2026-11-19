import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rasiko_rider/main.dart';

void main() {
  test('USB HTTP origin requires explicit debug opt-in and loopback', () {
    expect(validServerOrigin('http://127.0.0.1:8001'), false);
    expect(validServerOrigin('http://127.0.0.1:8001', allowUsb: true), true);
    expect(validServerOrigin('http://192.168.1.2:8001', allowUsb: true), false);
    expect(validServerOrigin('https://rasiko.in'), true);
    expect(validServerOrigin('https://user:pass@rasiko.in'), false);
  });
  test('HTML 404 becomes actionable error without exposing response contents',
      () async {
    final api = Api(
        baseUrl: 'https://example.test',
        client: MockClient((request) async {
          return http.Response('<html>private diagnostic details</html>', 404);
        }));
    await expectLater(
        api.call('register/', {'invitation': 'test-only'}),
        throwsA(predicate((Object e) =>
            e.toString().contains('HTTP 404') &&
            e.toString().contains('Rider service unavailable') &&
            !e.toString().contains('private diagnostic'))));
  });

  test('JSON registration errors and successful responses are preserved',
      () async {
    final denied = Api(
        client: MockClient((request) async =>
            http.Response('{"error":"Invitation expired"}', 400)));
    await expectLater(
        denied.call('register/', {}),
        throwsA(predicate(
            (Object e) => e.toString().contains('Invitation expired'))));
    final success = Api(
        client: MockClient(
            (request) async => http.Response('{"token":"test-token"}', 200)));
    expect((await success.call('login/', {}))['token'], 'test-token');
  });

  test('offers and delivery history accept list responses', () async {
    final api = Api(
        baseUrl: 'https://example.test',
        client: MockClient((request) async => http.Response('[]', 200)));
    expect(await api.call('offers/'), isEmpty);
    expect(await api.call('deliveries/'), isEmpty);
  });

  test('scalar JSON is rejected', () async {
    final api =
        Api(client: MockClient((request) async => http.Response('true', 200)));
    await expectLater(api.call('login/', {}), throwsException);
  });
}
