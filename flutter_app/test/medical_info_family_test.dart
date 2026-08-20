// Widget-level smoke for the intake family-history section (TODO G13).
//
// The payload projection is covered in voice_kernel_test; this checks the part a pure
// function cannot: that the section actually renders on the patient critical path and
// that adding a row works. A crash here would block every consultation.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/features/patient/medical_info_page.dart';

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  Future<void> pumpPage(WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.light,
          home: const MedicalInfoPage(
            args: {'complaintId': 'c1', 'complaintName': 'Hematuria', 'complaintText': 'x'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('past-history rows expose the stillHas checkbox', (tester) async {
    // `stillHas` was hardcoded true with no UI, so every resolved condition reached the
    // doctor as ongoing — silently wrong clinical data (TODO §G medium).
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await pumpPage(tester);

    final before = find.byType(Checkbox).evaluate().length;
    await tester.tap(find.text(t('intake.medicalInfo.history.add')));
    await tester.pumpAndSettle();

    expect(
      find.byType(Checkbox).evaluate().length,
      greaterThan(before),
      reason: '新增病史列後沒有出現 stillHas 勾選框——資料會永遠送 true',
    );
    expect(find.byTooltip(t('intake.medicalInfo.history.stillHas')), findsOneWidget);
  });

  testWidgets('family-history section renders and accepts a row', (tester) async {
    // The page is tall; a small surface makes off-screen widgets un-tappable.
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await pumpPage(tester);

    final addLabel = t('intake.medicalInfo.family.add');
    expect(find.text(t('intake.medicalInfo.family.title')), findsOneWidget,
        reason: '家族病史區塊沒渲染出來——familyHistory 又會變成永遠空白');
    expect(find.text(addLabel), findsOneWidget);

    // No rows until the patient adds one (the section is optional).
    expect(find.text(t('intake.medicalInfo.relations.father')), findsNothing);

    await tester.tap(find.text(addLabel));
    await tester.pumpAndSettle();

    // A row = relation dropdown (defaulting to 'father') + a condition field.
    expect(find.text(t('intake.medicalInfo.relations.father')), findsWidgets);
    expect(find.text(t('intake.medicalInfo.family.conditionPlaceholder')), findsWidgets);
  });

  testWidgets('family history has a "none" checkbox like the other three sections', (tester) async {
    // D-10: without it the patient cannot say 「沒有家族病史」, so the backend can only
    // tell 「沒填」 from 「有填」 — `no_family_history` stayed a dead branch in
    // patient_context.build_patient_info and §3b re-asked the urological-cancer family
    // history every session.
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await pumpPage(tester);

    final noneLabel = t('intake.medicalInfo.family.noneLabel');
    expect(find.text(noneLabel), findsOneWidget);
    // The label must be real copy, not the key echoed back by a missing translation.
    expect(noneLabel, isNot(contains('intake.medicalInfo')));

    // Ticking it collapses the rows: rows kept alive behind a ticked box are invisible
    // data that submit() drops, while the payload claims the patient denied it.
    await tester.tap(find.text(t('intake.medicalInfo.family.add')));
    await tester.pumpAndSettle();
    expect(find.text(t('intake.medicalInfo.family.conditionPlaceholder')), findsWidgets);

    // Tap the checkbox itself (the label is not a tap target here).
    final noneRow = find.ancestor(of: find.text(noneLabel), matching: find.byType(Row)).first;
    await tester.tap(find.descendant(of: noneRow, matching: find.byType(Checkbox)));
    await tester.pumpAndSettle();

    expect(find.text(t('intake.medicalInfo.family.conditionPlaceholder')), findsNothing,
        reason: '勾了「無家族病史」還留著輸入列＝看不見的資料，送出時會被靜默丟掉');
    expect(find.text(t('intake.medicalInfo.family.add')), findsNothing);
  });
}
