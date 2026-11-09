import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rasiko_rider/main.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  testWidgets('invitation registration is present and rider UI supports Hindi',
      (tester) async {
    await tester.pumpWidget(const RiderApp());
    await tester.pumpAndSettle();
    expect(find.text('Rasiko Rider'), findsOneWidget);
    expect(find.text('Invitation code (first login)'), findsOneWidget);
    expect(find.text('Register with invitation'), findsOneWidget);
    await tester.tap(find.byType(DropdownButton<int>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('हिन्दी').last);
    await tester.pumpAndSettle();
    expect(find.text('रासिको राइडर'), findsOneWidget);
    expect(find.text('ईमेल'), findsOneWidget);
    expect(find.text('पासवर्ड'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });

  testWidgets('Gujarati login remains readable at a narrow phone width',
      (tester) async {
    tester.view.physicalSize = const Size(320, 740);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RiderApp());
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButton<int>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('ગુજરાતી').last);
    await tester.pumpAndSettle();
    expect(find.text('રાસિકો રાઇડર'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });
}
