import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/features/admin/screens/user_management_page.dart';

import 'support/api_stub.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(Locales.loadAll);

  testWidgets('403 replaces account controls with a permission message', (tester) async {
    installApiStub((_) => ResponseBody.fromString('{}', 403));
    await tester.pumpWidget(MaterialApp(theme: AppTheme.light, home: const UserManagementPage()));
    await tester.pumpAndSettle();
    expect(find.text('只有系統管理員可以管理帳號。'), findsOneWidget);
    expect(find.byIcon(Icons.person_add_alt), findsNothing);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('authorized list is visible until a change returns 403', (tester) async {
    installApiStub((request) {
      if (request.method == 'PUT') return ResponseBody.fromString('{}', 403);
      return {
        'data': [{'id': 'fixture', 'name': 'Fixture', 'role': 'doctor', 'is_active': true}],
        'pagination': {'total_count': 1, 'has_more': false},
      };
    });
    await tester.pumpWidget(MaterialApp(theme: AppTheme.light, home: const UserManagementPage()));
    await tester.pumpAndSettle();
    expect(find.text('Fixture'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(find.byIcon(Icons.person_add_alt), findsOneWidget);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(find.text('只有系統管理員可以管理帳號。'), findsOneWidget);
    expect(find.text('Fixture'), findsNothing);
    expect(find.byType(TextField), findsNothing);
    expect(find.byIcon(Icons.person_add_alt), findsNothing);
  });
}
