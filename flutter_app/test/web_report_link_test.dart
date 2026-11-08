import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/doctor/screens/soap_report_page.dart';

void main() {
  test('沒注入 WEB_BASE 時不給連結（按鈕不顯示）', () {
    expect(webReportUrl('', 'zh-TW', 's1'), isNull);
    expect(webReportUrl('   ', 'zh-TW', 's1'), isNull);
  });

  test('組出網頁報告路由，去掉結尾斜線', () {
    expect(
      webReportUrl('https://gu-voice.example.app/', 'ja-JP', '7f1c-uuid').toString(),
      'https://gu-voice.example.app/ja-JP/reports/7f1c-uuid',
    );
  });
}
