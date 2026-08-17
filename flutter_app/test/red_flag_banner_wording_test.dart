// 病患面資訊邊界的回歸守衛（不變式 #11 措辭 + 醫師向欄位不外流）。
//
// 背景（真跑 torsion_critical_zh 的實際 payload，2026-07-27）：
//   payload.description      = 「可能為睪丸扭轉,需要在 6 小時內處理以避免壞死」
//   payload.suggestedActions = [..., '立即安排急診評估']
// 這兩個欄位是**醫師向**的臨床推理與醫囑處置。部署情境是院內候診 kiosk，病患已經
// 坐在泌尿科候診區 —— 叫他「立即安排急診評估」既是錯誤指引又造成恐慌。
//
// 這一輪的防線分三層，本檔守其中兩層的靜態部分：
//   L1 後端：送往病患的 red_flag_alert payload 結構性地不含醫師向欄位（backend 側）
//   L2 前端 ingest：React 的 on('red_flag_alert') 不把這兩個欄位寫進 store
//   L3 前端 render：兩份 UI 都只渲染 title，行動指引固定走 redFlag.patientNotice
//
// frontend/ 沒有單元測試 runner（package.json 裡沒有 vitest/jest，只有需要真後端的
// Playwright），所以 React 那份的靜態守衛也放在這裡 —— 這是唯一會在 CI 跑到的地方。

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';

/// flutter test 的 cwd 是 flutter_app/，repo 根在上一層。
File _repoFile(String relative) => File('${Directory.current.parent.path}/$relative');

/// 病患面禁語（不變式 #11）：部署情境是院內候診 kiosk，病患已坐在候診區，
/// 叫他「盡速就醫／立即急診」既是錯誤指引又造成恐慌。
const _bannedPatientWording = <String>[
  '盡速就醫', '儘速就醫', '尽速就医', '立即就醫', '立刻就醫',
  '立即急診', '立刻急診', '趕快去醫院', '前往急診', '掛急診',
  'emergency room', 'go to the er', 'seek emergency', 'urgent care',
  '救急外来', '応急室', '急诊', '응급실', 'cấp cứu',
];

/// 同一份翻譯在倉庫裡的三份拷貝。`frontend/public/locales` 是 vite build 鏡像，
/// 上一版只掃 flutter 那份 —— 病患實際看到的是 **public/ 那份**（前端執行期從
/// public/locales 載入 namespace），漏掃它等於漏掉真正上線的那份文案。
const _localeCopies = <String>[
  'frontend/src/i18n/locales',
  'frontend/public/locales',
  'flutter_app/assets/locales',
];

/// 去掉註解後的原始碼。註解本身會提到被禁的識別字（「不可退回 reviewNotes」之類的
/// 說明），那不算違規；只有真正的程式碼才受檢。`//` 行註解與 `/* */` 區塊註解
/// （TSX 的 `{/* ... */}`、Dart 的 `/* ... */`）都要剝掉。
String _codeOnly(String src, {required String lineComment}) {
  final noBlock = src.replaceAll(RegExp(r'/\*.*?\*/', dotAll: true), '');
  return noBlock
      .split('\n')
      .where((l) => !l.trimLeft().startsWith(lineComment))
      .join('\n');
}

/// 從 backend/app/utils/i18n_messages.py 挖出某個 key 的五語文案。
///
/// 為什麼要跨語言硬讀 Python 原始碼：後端這輪把病患指引改成由 payload 下發
/// （`ws.red_flag_patient_notice_{notified,flagged}`），前端 locale 那份只在
/// payload 缺欄位時當 fallback。兩邊若各自演化，就會回到「後端改了、前端還留
/// 舊文案」——那正是本輪要修的缺陷之一。這裡逐字比對把它釘死。
///
/// 解析法：找到 `"<key>": {` 之後到第一個 `},` 為止的區塊，逐行抓
/// `"<lng>": "<value>",`。後端若把某條改成多行括號串接（該檔其他 key 有這種
/// 寫法），這裡會抓不到 → 測試**失敗**而非靜默放行，符合預期。
Map<String, String> _backendMessage(String key) {
  final src = _repoFile('backend/app/utils/i18n_messages.py').readAsStringSync();
  final start = src.indexOf('"$key": {');
  if (start < 0) return const {};
  final end = src.indexOf('},', start);
  if (end < 0) return const {};
  final block = src.substring(start, end);
  final out = <String, String>{};
  for (final m in RegExp(r'"([a-z]{2}-[A-Z]{2})":\s*"((?:[^"\\]|\\.)*)"').allMatches(block)) {
    out[m.group(1)!] = m.group(2)!.replaceAll(r'\"', '"').replaceAll(r'\\', r'\');
  }
  return out;
}

Map<String, dynamic>? _redFlagNs(String copy, String lng) {
  final f = _repoFile('$copy/$lng/conversation.json');
  if (!f.existsSync()) return null;
  final root = json.decode(f.readAsStringSync());
  if (root is! Map) return null;
  final rf = root['redFlag'];
  return rf is Map ? rf.cast<String, dynamic>() : null;
}

void main() {
  group('L2/L3：醫師向欄位不得進入病患端', () {
    test('React 病患問診頁：red_flag_alert 不 ingest description / suggestedActions', () {
      final code = _codeOnly(
        _repoFile('frontend/src/screens/patient/ConversationPage.tsx').readAsStringSync(),
        lineComment: '//',
      );
      // ingest 層（結構性防線）：payload 的醫師向欄位一個都不准讀進 store。
      // 這比只掃 render 層的 `{alert.description}` 強 —— 就算日後有人在 JSX
      // 裡寫回來，store 裡沒有值也印不出東西。
      expect(RegExp(r'data\.description').hasMatch(code), isFalse,
          reason: 'React 病患端把紅旗 description（醫師向臨床推理）寫進 store');
      expect(RegExp(r'data\.suggestedActions').hasMatch(code), isFalse,
          reason: 'React 病患端把紅旗 suggestedActions（醫囑處置）寫進 store');
      // render 層（第二道）：不得把這兩個欄位印出來。
      expect(RegExp(r'\{\s*alert\.(description|suggestedActions)').hasMatch(code), isFalse,
          reason: 'React 病患端渲染了紅旗醫師向欄位，違反 kiosk 措辭鐵律');
      expect(code.contains("t('conversation:redFlag.patientNotice')"), isTrue,
          reason: 'React 紅旗橫幅少了病患面的 kiosk 指引 patientNotice');
    });

    test('Flutter 病患問診頁：紅旗橫幅只渲染 title', () {
      final code = _codeOnly(
        _repoFile('flutter_app/lib/features/voice/screens/conversation_page.dart')
            .readAsStringSync(),
        lineComment: '//',
      );
      // render 層（第二道）：欄位名任一寫法都擋。
      expect(RegExp(r'\bf\.(description|suggestedActions)\b').hasMatch(code), isFalse,
          reason: 'Flutter 病患端渲染了紅旗醫師向欄位，違反 kiosk 措辭鐵律');
      expect(code.contains("t('conversation.redFlag.patientNotice')"), isTrue,
          reason: 'Flutter 紅旗橫幅少了病患面的 kiosk 指引 patientNotice（本地保守版 fallback）');
      // 後端下發的 patientNotice 要優先於本地 fallback（後端才知道有沒有真的
      // 通知到醫師；前端自己選字就可能對病患說謊）。
      expect(code.contains('_sharedPatientNotice'), isTrue,
          reason: 'Flutter 紅旗橫幅沒有優先採用後端下發的 patientNotice');
    });

    test('Flutter 紅旗 ingest / 型別層不得保留醫師向欄位（結構性防線）', () {
      // 2026-07-27 Gate 補上。原本 Flutter 只有 render 層守衛，型別與 ingest 仍
      // 照收 description / suggestedActions —— 少了 React 已有的結構性防線。
      // store 裡沒有值，日後有人在 widget 裡想印也印不出東西。
      final model = _codeOnly(
        _repoFile('flutter_app/lib/features/voice/models/chat_message.dart')
            .readAsStringSync(),
        lineComment: '//',
      );
      final redFlagClass = model.substring(model.indexOf('class RedFlagEvent'));
      expect(RegExp(r'\bdescription\b').hasMatch(redFlagClass), isFalse,
          reason: 'RedFlagEvent 型別仍保留 description（醫師向臨床推理）');
      expect(RegExp(r'\bsuggestedActions\b').hasMatch(redFlagClass), isFalse,
          reason: 'RedFlagEvent 型別仍保留 suggestedActions（醫囑處置）');
      expect(RegExp(r'\bpatientNotice\b').hasMatch(redFlagClass), isTrue,
          reason: 'RedFlagEvent 少了 patientNotice，Flutter 無法顯示後端二選一的病患指引');

      final controller = _codeOnly(
        _repoFile('flutter_app/lib/features/voice/state/conversation_controller.dart')
            .readAsStringSync(),
        lineComment: '//',
      );
      final onRedFlag = controller.substring(controller.indexOf('void _onRedFlag'));
      final body = onRedFlag.substring(0, onRedFlag.indexOf('\n  }'));
      expect(RegExp(r"\['description'\]").hasMatch(body), isFalse,
          reason: 'Flutter ingest 仍把紅旗 description 讀進 state');
      expect(RegExp(r"\['suggestedActions'\]").hasMatch(body), isFalse,
          reason: 'Flutter ingest 仍把紅旗 suggestedActions 讀進 state');
      expect(RegExp(r"\['patientNotice'\]").hasMatch(body), isTrue,
          reason: 'Flutter ingest 沒有讀後端下發的 patientNotice');
    });

    test('病患場次詳情頁不得把醫師的 reviewNotes 當成醫囑顯示', () {
      // reviewNotes = SOAP 報告的「審閱備註」，是醫師寫給自己/同事的內部註記。
      // 舊寫法在 patientEducation 為空時退回它 —— 後端這輪對 patientEducation
      // 加了出口過濾後，「為空」會變成常態，那個洩漏也會跟著變成常態。
      final tsx = _codeOnly(
        _repoFile('frontend/src/screens/patient/PatientSessionDetailPage.tsx')
            .readAsStringSync(),
        lineComment: '//',
      );
      expect(tsx.contains('reviewNotes'), isFalse,
          reason: 'React 病患場次詳情頁引用了 reviewNotes（醫師向內部註記）');

      final dart = _codeOnly(
        _repoFile('flutter_app/lib/features/patient/patient_session_detail_page.dart')
            .readAsStringSync(),
        lineComment: '//',
      );
      expect(dart.contains('reviewNotes'), isFalse,
          reason: 'Flutter 病患場次詳情頁引用了 reviewNotes（醫師向內部註記）');
    });
  });

  group('紅旗橫幅文案：五語齊備 × 三份拷貝一致 × 措辭合規', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });

    // 直接查該語言自己的 JSON，不經過 t() —— t() 有 fallback chain，
    // ja/ko/vi 缺 key 也會回英文而讓測試假通過。
    test('patientNotice / generic 在五語 × 三份拷貝都存在且完全一致', () {
      for (final lng in supportedLanguages) {
        // 以 src 那份為 source of truth。
        final ref = _redFlagNs(_localeCopies.first, lng);
        expect(ref, isNotNull, reason: '${_localeCopies.first}/$lng 缺 conversation.redFlag');

        for (final key in ['patientNotice', 'generic']) {
          final refVal = ref![key];
          expect(refVal, isA<String>(),
              reason: '${_localeCopies.first}/$lng 缺 redFlag.$key');
          expect((refVal as String).trim(), isNotEmpty,
              reason: '$lng 的 redFlag.$key 是空字串 → 病患看到空白');

          for (final copy in _localeCopies.skip(1)) {
            final got = _redFlagNs(copy, lng)?[key];
            expect(got, refVal,
                reason: '$copy/$lng 的 redFlag.$key 與 ${_localeCopies.first} 不一致'
                    '（build 鏡像／flutter asset 未同步）');
          }
        }
      }
    });

    test('Locales.loadAll() 載進來的 flutter asset 也帶著同一份文案', () {
      // 上一條比的是檔案內容；這條確認 flutter 執行期真的載得到（asset 未宣告
      // 或 pubspec 漏了目錄時，檔案在但 runtime 讀不到）。
      for (final lng in supportedLanguages) {
        final ns = Locales.forLng(lng)?['conversation'];
        final rf = (ns is Map) ? ns['redFlag'] : null;
        expect(rf, isA<Map>(), reason: 'runtime 載不到 $lng 的 conversation.redFlag');
        for (final key in ['patientNotice', 'generic']) {
          expect((rf as Map)[key], _redFlagNs(_localeCopies.first, lng)![key],
              reason: 'runtime 讀到的 $lng redFlag.$key 與源頭不一致');
        }
      }
    });

    test('前端 fallback 文案逐字等於後端保守版 ws.red_flag_patient_notice_flagged', () {
      // 後端在 red_flag_alert payload 帶 patientNotice，依「有沒有真的建立醫師
      // 通知」在 _notified / _flagged 之間二選一。前端 locale 的
      // redFlag.patientNotice 只是 payload 缺欄位時的 fallback，必須取**保守**
      // 的 _flagged 版：否則沒真的通知到醫師時，病患會看到「已通知現場醫護人員」
      // ——那就是上一輪被抓到的「對病患說謊」。
      final backend = _backendMessage('ws.red_flag_patient_notice_flagged');
      expect(backend.keys.toSet(), supportedLanguages.toSet(),
          reason: '解析後端 i18n_messages.py 失敗或該 key 五語不齊');
      for (final lng in supportedLanguages) {
        for (final copy in _localeCopies) {
          expect(_redFlagNs(copy, lng)?['patientNotice'], backend[lng],
              reason: '$copy/$lng 的 redFlag.patientNotice 與後端 '
                  'ws.red_flag_patient_notice_flagged 不一致（後端改了、前端沒跟）');
        }
      }
    });

    test('後端 notified 版也守同一條措辭鐵律（病患真正會看到的是這一版）', () {
      // payload 帶回來的那句才是常態顯示內容，禁語檢查不能只守前端 fallback。
      final backend = _backendMessage('ws.red_flag_patient_notice_notified');
      expect(backend.keys.toSet(), supportedLanguages.toSet(),
          reason: '解析後端 i18n_messages.py 失敗或該 key 五語不齊');
      for (final entry in backend.entries) {
        for (final phrase in _bannedPatientWording) {
          expect(entry.value.toLowerCase().contains(phrase.toLowerCase()), isFalse,
              reason: '後端 ws.red_flag_patient_notice_notified/${entry.key} '
                  '用了被禁止的措辭「$phrase」');
        }
      }
    });

    test('三份拷貝的 patientNotice 都不得含糊叫病患自己去就醫（病患已在候診區）', () {
      for (final copy in _localeCopies) {
        for (final lng in supportedLanguages) {
          final notice = (_redFlagNs(copy, lng)?['patientNotice'] as String?)?.toLowerCase();
          expect(notice, isNotNull, reason: '$copy/$lng 缺 patientNotice');
          for (final phrase in _bannedPatientWording) {
            expect(notice!.contains(phrase.toLowerCase()), isFalse,
                reason: '$copy/$lng 的 patientNotice 用了被禁止的措辭「$phrase」');
          }
        }
      }
    });
  });
}
