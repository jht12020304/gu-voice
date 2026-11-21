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
}
