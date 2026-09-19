// Smoke test only — proves the harness app builds and renders its main
// controls without a real API/LiveKit backend or Android device. The real
// E2EE interoperability tests this harness exists for require the manual
// procedure in sdk/flutter/README.md's "External E2EE device test
// harness" section, run against a real Android emulator/device — nothing
// in this repo's automated suite can substitute for that.

import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';

import 'package:e2ee_test_harness/main.dart';

void main() {
  testWidgets('harness renders its main actions without crashing', (WidgetTester tester) async {
    // The default test surface (800x600 logical px) is far smaller than
    // any real phone and overflows this full-screen layout; simulate a
    // realistic device viewport instead of shrinking the UI to fit an
    // artificially tiny window.
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const E2EETestHarnessApp());
    await tester.pumpAndSettle();

    expect(find.text('AyurEze E2EE Test Harness'), findsOneWidget);
    expect(find.text('1. Authenticate'), findsOneWidget);
    expect(find.text('2a. Create + Join + Publish (Test B/C first)'), findsOneWidget);
    expect(find.text('2b. Join Existing (Test A/C second)'), findsOneWidget);
    expect(find.text('E2EE track states (live)'), findsOneWidget);
    expect(find.text('No tracks yet'), findsOneWidget);
  });
}
