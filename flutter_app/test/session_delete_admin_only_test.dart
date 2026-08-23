// 刪除問診（2026-08-23 admin「最高權限」）的前端守衛。
//
// 兩件事只要有一件破了，這個功能就從「管理員專屬」變成別的東西：
//   1. 刪除入口在頁面上沒有被 `isAdmin` 包住 → 一般醫師看得到一顆按不了的鈕
//      （後端會 403），或更糟——哪天後端放寬了就真的能刪。
//   2. 五語系少了任何一個刪除相關字串 → 那個語系的醫師看到的是 key 本身，
//      而這是**破壞性動作**的確認框，看不懂就等於盲按。
//
// 都用靜態檢查（讀原始碼與 assets/locales），不起 app、不打網路。

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/router/lng.dart';

File _appFile(String relative) => File('${Directory.current.path}/$relative');

const _detailPage = 'lib/features/doctor/screens/session_detail_page.dart';

/// 刪除相關的六個 key（session.doctor.detail.* 底下）。
const _deleteKeys = [
  'deleteSession',
  'deleteSessionTitle',
  'deleteSessionConfirm',
  'deleting',
  'deleteSuccess',
  'deleteError',
];

void main() {
  test('刪除入口被 isAdmin 包住', () {
    final code = _appFile(_detailPage).readAsStringSync();
    expect(code.contains('_confirmDelete'), isTrue,
        reason: '場次詳情頁沒有刪除入口了？（本測試要跟著改）');
    // 取「isAdmin 判斷」到「刪除按鈕」之間的距離：入口必須在 admin 判斷之內。
    final adminIdx = code.indexOf('isAdmin');
    final buttonIdx = code.indexOf('onPressed: _deleting ? null : _confirmDelete');
    expect(adminIdx, greaterThan(-1), reason: '刪除入口沒有任何 isAdmin 守衛');
    expect(buttonIdx, greaterThan(adminIdx),
        reason: '刪除按鈕出現在 isAdmin 判斷之前——等於對所有醫師顯示');
  });

  test('刪除是破壞性動作：確認框先問過才會呼叫 API', () {
    final code = _appFile(_detailPage).readAsStringSync();
    final confirmIdx = code.indexOf('void _confirmDelete');
    final apiIdx = code.indexOf('_api.deleteSession');
    expect(confirmIdx, greaterThan(-1), reason: '沒有確認框，刪除變成一鍵直刪');
    expect(apiIdx, greaterThan(-1));
    expect(code.contains("t('session.doctor.detail.deleteSessionConfirm')"), isTrue,
        reason: '確認框沒有說明刪掉之後會發生什麼事');
  });

  test('五語系都有刪除相關文案，且不是空字串', () {
    for (final lng in supportedLanguages) {
      final raw = json.decode(
        _appFile('assets/locales/$lng/session.json').readAsStringSync(),
      ) as Map;
      final detail = (raw['doctor'] as Map)['detail'] as Map;
      for (final key in _deleteKeys) {
        final value = detail[key];
        expect(value, isA<String>(),
            reason: '$lng 缺 session.doctor.detail.$key——那個語系會顯示 key 本身');
        expect((value as String).trim(), isNotEmpty,
            reason: '$lng 的 $key 是空字串');
      }
    }
  });

  test('確認框文案有講「資料還在、只是不再出現」（軟刪除語意）', () {
    // 這條擋的是「文案寫成永久刪除」——後端做的是軟刪除，寫成不可逆會讓
    // 使用者以為救不回來而不敢用，或反過來以為已經徹底清除。
    final zh = json.decode(
      _appFile('assets/locales/zh-TW/session.json').readAsStringSync(),
    ) as Map;
    final confirm =
        ((zh['doctor'] as Map)['detail'] as Map)['deleteSessionConfirm'] as String;
    expect(confirm.contains('無法復原'), isFalse,
        reason: '後端是軟刪除，文案不該宣稱無法復原');
    expect(confirm.contains('資料'), isTrue,
        reason: '文案應說明資料的去向（仍保留、需管理者救回）');
  });
}
