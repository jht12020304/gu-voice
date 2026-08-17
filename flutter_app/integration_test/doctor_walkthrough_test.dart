// 醫師端走查：登入 → sessions 列表（血尿×2 場、其中一場 aborted_red_flag 帶 critical 紅旗）
// → session detail（指派給自己）→ dashboard（統計數字非空）→ alerts 頁看紅旗、開 detail、
// 確認處置（acknowledge）→ reports 頁開啟 SOAP 報告，驗 S/O/A/P 內容區塊與逐字稿分頁。
// 對真後端跑（不打真 OpenAI——場次與 SOAP 都是既有種子資料，只讀不觸發生成）。
//
// 斷言一律用資料特徵（「血尿」「睪丸劇痛」、aborted_red_flag 狀態、critical 嚴重度），
// 不寫死任何 session/alert id——這樣同一支測試可以在任何已有種子資料的環境重跑。
//
// ⚠️ P3 走查發現的測試脆弱性（已修）：早期版本用 `find.text(redFlagBadge).first` 直接鎖定
// sessions 列表裡「第一張帶紅旗徽章的卡」，隱含假設 DB 只有一場帶紅旗徽章的場次。實際環境
// 常常不只一場（例如「頻尿、排尿疼痛／尿路敗血症」這種場次也會 aborted_red_flag），順序也不
// 保證，於是點錯卡、後續斷言全部連鎖失敗——這是測試本身的假設錯誤，不是產品缺陷。現在改用
// `_tapBloodyUrineRedFlagTile()`：先用「主訴文字＝血尿」交集「有紅旗徽章」縮候選，若仍有多個
// candidate 就逐一點進 detail 驗 `redFlagReason` 真的含「睪丸劇痛」才收，全程不假設列表數量
// 或順序。
//
// ⚠️ dashboard 統計數字是「該醫師自己名下」的場次（backend `_resolve_doctor_scope`：
// role==doctor 時一律強制 `Session.doctor_id == current_user.id`，見
// backend/app/services/dashboard_service.py），不是全院場次。種子資料的場次
// `doctor_id` 一開始是 NULL（未指派），所以這支測試會先在 session detail 頁用
// 「指派給我」把兩場種子場次認領到登入的醫師帳號下，dashboard 數字才會非零——
// 這不是繞過產品邏輯，是真實醫師工作流程的一部分（醫師要先認領場次才會出現在自己
// 的統計裡），重跑此測試是冪等的（已指派過的場次不會重複指派或報錯）。
//
// 跑法：
//
//   flutter drive --driver=test_driver/integration_test.dart \
//     --target=integration_test/doctor_walkthrough_test.dart \
//     -d web-server --web-port=5175 --browser-name=chrome \
//     --web-browser-flag=--use-fake-ui-for-media-stream \
//     --web-browser-flag=--use-fake-device-for-media-stream \
//     --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
//     --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws \
//     --dart-define=E2E_DOCTOR_EMAIL=... --dart-define=E2E_DOCTOR_PASSWORD=...
//
// 前提：DB 裡本月至少有兩場「血尿」場次，其中一場 status=completed 且已生成 SOAP，
// 另一場 status=aborted_red_flag、帶 critical 紅旗（trigger 含「睪丸」）且已生成 SOAP。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/screens/alert_detail_page.dart';
import 'package:gu_voice/features/doctor/screens/alert_list_page.dart';
import 'package:gu_voice/features/doctor/screens/report_list_page.dart';
import 'package:gu_voice/features/doctor/screens/session_detail_page.dart';
import 'package:gu_voice/features/doctor/screens/session_list_page.dart';
import 'package:gu_voice/features/doctor/screens/soap_report_page.dart';
import 'package:gu_voice/data/api/reports_api.dart';
import 'package:gu_voice/data/api/alerts_api.dart';

const _email = String.fromEnvironment('E2E_DOCTOR_EMAIL');
const _password = String.fromEnvironment('E2E_DOCTOR_PASSWORD');

Future<void> _pumpFor(WidgetTester tester, Duration total, {bool Function()? until}) async {
  final deadline = total.inMilliseconds ~/ 250;
  for (var i = 0; i < deadline; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (until != null && until()) return;
  }
}

// Web 陷阱（見 patient_text_flow_test.dart）：合成 tap 不等於真實 DOM focus，
// 第二次起的 enterText 若不先手動 tap+pump 該輸入框，會靜默沒送出。這支對每一次
// enterText 都先做這個動作，圖個保險。
Future<void> _typeInto(WidgetTester tester, Finder field, String text) async {
  await tester.tap(field);
  await tester.pump();
  await tester.enterText(field, text);
  await tester.pumpAndSettle();
}

// 依「hint 文字前一個 Text 就是數值」的版面關係讀出 dashboard 統計卡數字，避免解析
// widget 樹結構——_statCard 固定是 Column[title, value, hint] 三個 Text。
String? _valueBeforeText(WidgetTester tester, String hint) {
  final texts = tester.widgetList<Text>(find.byType(Text)).map((w) => w.data).toList();
  final idx = texts.indexOf(hint);
  if (idx <= 0) return null;
  return texts[idx - 1];
}

// 定位「血尿」×「帶紅旗徽章」那張 ListTile。P3 走查發現：DB 可能同時有多場帶紅旗徽章的
// 場次（例如另一個主訴「頻尿、排尿疼痛」也會 aborted_red_flag），單用
// `find.text(redFlagBadge).first` 找 ListTile 祖先會點錯場次。這裡先用「主訴文字＝血尿」
// 交集「有紅旗徽章」把候選縮到只剩「血尿」場次裡帶紅旗的那些；如果種子資料重複灌了不只
// 一場（例如同一支測試被重跑、或種子腳本重灌），逐一點進 detail 驗證 redFlagReason 真的
// 含「睪丸劇痛」才收——不對的就返回列表換下一個候選，而不是賭第一個候選就是對的。
Future<void> _tapBloodyUrineRedFlagTile(WidgetTester tester, GoRouter router, String redFlagBadge) async {
  bool tileMatches(Finder tile) =>
      find.descendant(of: tile, matching: find.text('血尿')).evaluate().isNotEmpty &&
      find.descendant(of: tile, matching: find.text(redFlagBadge)).evaluate().isNotEmpty;

  final candidateCount = find.byType(ListTile).evaluate().where((e) {
    final tile = find.byWidget(e.widget);
    return tileMatches(tile);
  }).length;
  expect(candidateCount, greaterThan(0),
      reason: '找不到任何「血尿」＋紅旗徽章組合的 ListTile（種子資料應該至少有一場血尿的 '
          'aborted_red_flag 場次）');

  for (var attempt = 0; attempt < candidateCount; attempt++) {
    // 每次重新查詢：上一輪若「返回列表」，widget tree 會重建，舊的 Finder index 可能失效。
    final tiles = find.byType(ListTile);
    Finder? target;
    var seen = 0;
    for (var i = 0; i < tiles.evaluate().length; i++) {
      final tile = tiles.at(i);
      if (!tileMatches(tile)) continue;
      if (seen == attempt) {
        target = tile;
        break;
      }
      seen++;
    }
    if (target == null) break; // 候選數比想像的少（例如上一輪誤判），停止嘗試。

    await tester.tap(target, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionDetailPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    if (find.textContaining('睪丸劇痛').evaluate().isNotEmpty) return; // 找到目標場次。

    // 不是目標場次：回列表換下一個候選。
    router.go(prefixLngToPath('/sessions', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
  }
  fail('把所有「血尿」＋紅旗徽章的候選 tile 都點過一輪，沒有一場的 redFlagReason 含'
      '「睪丸劇痛」——種子資料可能已經變動，這支測試假設的紅旗場次找不到了');
}

// Reports 列表版的同一個問題：`find.text(redFlagBadge).first` 賭第一列就是目標場次的報告。
// 列表按 created_at 新到舊排，而 DB 裡帶紅旗徽章的報告不只一份（實測有「大量血尿」「尿路敗血症」
// 等其他紅旗場次，且 e2e 每跑一次就多一份），所以第一列常常不是「睪丸劇痛」那份 —— 後面
// 「紅旗橫幅帶到睪丸劇痛」的斷言就會假性失敗。這裡照 `_tapBloodyUrineRedFlagTile` 的做法：
// 逐一點開紅旗報告候選，開到 SOAP 頁驗紅旗內容真的含「睪丸劇痛」才收，不對就回列表換下一個。
Future<void> _openTesticularRedFlagReport(
    WidgetTester tester, GoRouter router, String redFlagBadge) async {
  Future<void> backToList() async {
    router.go(prefixLngToPath('/reports', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(ReportListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();
  }

  final candidateCount = find.text(redFlagBadge).evaluate().length;
  for (var attempt = 0; attempt < candidateCount; attempt++) {
    // 每輪重查：回列表後 widget tree 會重建，舊 Finder 的 index 可能失效。
    final badges = find.text(redFlagBadge);
    if (attempt >= badges.evaluate().length) break;
    final tile = find.ancestor(of: badges.at(attempt), matching: find.byType(InkWell));
    if (tile.evaluate().isEmpty) continue;
    await tester.tap(tile.first, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SoapReportPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    if (find.textContaining('睪丸劇痛').evaluate().isNotEmpty) return; // 找到目標報告。
    await backToList();
  }
  fail('Reports 列表裡所有帶紅旗徽章的候選都點過一輪，沒有一份的紅旗內容含「睪丸劇痛」——'
      '種子資料可能已經變動，這支測試假設的紅旗場次報告找不到了');
}

// 進了 session detail 之後，若還沒指派給自己就點「指派給我」，等成功。已指派過（重跑
// 這支測試）就直接跳過，冪等。
Future<void> _ensureAssignedToMe(WidgetTester tester) async {
  final assignedLabel = t('session.doctor.detail.assignedToMe');
  if (find.text(assignedLabel).evaluate().isNotEmpty) return;
  final assignBtn = find.text(t('session.doctor.detail.assignToMe'));
  expect(assignBtn, findsOneWidget, reason: 'session detail 找不到「指派給我」按鈕');
  await tester.tap(assignBtn);
  await _pumpFor(tester, const Duration(seconds: 10),
      until: () => find.text(assignedLabel).evaluate().isNotEmpty);
  await tester.pumpAndSettle();
  expect(find.text(assignedLabel), findsOneWidget, reason: '指派給我後應該顯示「已指派給你」');
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('doctor walkthrough: sessions -> assign -> dashboard -> alerts -> reports', (tester) async {
    if (_email.isEmpty || _password.isEmpty) {
      markTestSkipped('未提供 E2E_DOCTOR_EMAIL / E2E_DOCTOR_PASSWORD，跳過');
      return;
    }
    // 醫師端頁面偏長（列表 + 卡片），小畫布會讓 off-screen widget 點不到。
    tester.view.physicalSize = const Size(1400, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    ApiClient.instance.init();
    await Locales.loadAll();
    await TokenStore.instance.clear();

    final container = ProviderContainer();
    addTearDown(container.dispose);
    ApiClient.instance.onAuthCleared = () => container.read(authProvider.notifier).forceLoggedOut();
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const App()),
    );
    await tester.pumpAndSettle();

    // ── 登入 ────────────────────────────────────────────────
    final loginFields = find.byType(TextField);
    expect(loginFields, findsAtLeast(2), reason: '登入頁應有 email / password');
    await _typeInto(tester, loginFields.at(0), _email);
    await _typeInto(tester, loginFields.at(1), _password);
    await tester.tap(find.byType(FilledButton).first);
    await _pumpFor(tester, const Duration(seconds: 15), until: () => container.read(authProvider).user != null);
    await tester.pumpAndSettle();
    final user = container.read(authProvider).user;
    expect(user, isNotNull, reason: '醫師登入失敗');
    expect(user!.isPatient, isFalse, reason: '這支測的是醫師/管理者帳號，登入結果不該是 patient');

    final router = container.read(routerProvider);

    // ── 跨端契約 regression guard（Decimal → JSON number）────
    // 曾經的缺陷（已修）：backend/app/schemas/report.py 的
    // `ai_confidence_score: Optional[Decimal]` 被 pydantic v2 用預設規則序列化成「字串」
    // （0.80 → "0.80"），而 flutter_app/lib/data/models/soap_report.dart 的
    // `(json['aiConfidenceScore'] as num?)` 硬轉型遇到 String 會直接丟 TypeError，
    // 例外又被上層 catch(_) 吞掉變成靜默失敗，殃及三個畫面：
    //   - ReportsApi.list()（Reports 列表頁）整批 .map() 拋例外 → 列表看起來是空的
    //   - ReportsApi.getReport()/getReportBySession()（session detail 查報告狀態、
    //     SoapReportPage 本體）同樣失敗 → 「查看報告」不出現、報告頁顯示「尚未生成」
    // 修法在後端 schema 層：backend/app/schemas/common.py 的 `JsonFloatDecimal`
    // （`Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]`），
    // 套用在 report.ai_confidence_score（×2，含 revision）與
    // conversation.audio_duration_seconds / stt_confidence 上——JSON 輸出一律 number，
    // Python 端與 DB numeric 寫入路徑不變。前端解析寫法刻意沒有動（防禦式解析是另一層決策）。
    // 這裡先直接打一次真 API：若後端哪天回頭把 Decimal 序列化成字串，會在這一行明確炸掉，
    // 而不是讓下面的 UI 斷言以難懂的「列表是空的」形式失敗。
    final probe = await ReportsApi().list(limit: 5);
    expect(probe.data, isNotEmpty,
        reason: 'ReportsApi().list() 回了空清單——DB 裡應該有已生成的 SOAP 報告；'
            '若後端把 ai_confidence_score 序列化回字串，整批解析會失敗');
    expect(probe.data.any((r) => r.aiConfidenceScore != null), isTrue,
        reason: '沒有任何一份報告解析出 aiConfidenceScore——正常生成的 SOAP 一定帶這個欄位，'
            '解析不出來代表後端又把 Decimal 序列化成字串了（跨端契約破口）');

    // ── Sessions 列表：兩場種子場次都要出現 ──────────────────
    router.go(prefixLngToPath('/sessions', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();

    expect(find.text('血尿'), findsAtLeast(2), reason: '兩場種子場次的主訴「血尿」沒有都出現在列表');
    final redFlagBadge = t('session.doctor.list.redFlagBadge');
    expect(find.text(redFlagBadge), findsAtLeast(1), reason: 'aborted_red_flag 場次的紅旗徽章沒出現在列表');

    // ── Session Detail（一般 completed 場次）：認領 + 開報告入口 ─
    // 篩到「已完成」，避開 aborted_red_flag，確保拿到的是 status==completed 的血尿場次。
    // 篩選籤的文案（session.doctor.list.tabCompleted = 「已完成」）跟列表每一列 StatusBadge
    // 的狀態文案（common.patient.home.statusCompleted）是同一個字串，裸 find.text 會同時
    // 命中籤與徽章而讓 tap() 因為多重命中直接拋錯 —— 鎖到 ChoiceChip 這個祖先才唯一。
    await tester.tap(find.widgetWithText(ChoiceChip, t('session.doctor.list.tabCompleted')));
    await tester.pumpAndSettle();
    final completedTiles = find.byType(ListTile);
    expect(completedTiles, findsAtLeast(1), reason: '篩「已完成」後列表是空的，種子資料應該有 completed 血尿場次');
    await tester.tap(completedTiles.first, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionDetailPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _ensureAssignedToMe(tester);
    // 等 report status 查詢（非同步）跑完。
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();
    // 曾經因為 ai_confidence_score 型別錯誤，這裡的 report 狀態查詢會靜默失敗，
    // _reportStatus 停留在 null，session detail 誤判成「還沒生成報告」而顯示「產生報告」。
    // 後端 JsonFloatDecimal 修好之後，已生成 SOAP 的 completed 場次應該顯示「查看報告」。
    expect(find.text(t('session.doctor.detail.viewReport')), findsOneWidget,
        reason: 'completed 場次已生成 SOAP，session detail 應該要能直接開「查看報告」'
            '（若這裡又變回「產生報告」，先確認 GET /api/v1/reports 的 ai_confidence_score '
            '是不是又變成字串）');
    expect(find.text(t('session.doctor.detail.generateReport')), findsNothing,
        reason: '已有 SOAP 的場次不該顯示「產生報告」');

    // ── Session Detail（紅旗場次）：認領 ─────────────────────
    router.go(prefixLngToPath('/sessions', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    // 用「血尿」主訴文字 + 紅旗徽章組合鎖定目標 tile（DB 可能有多場帶紅旗徽章的場次，
    // 見 `_tapBloodyUrineRedFlagTile` 註解），點進去後已經驗過 redFlagReason 是「睪丸劇痛」。
    await _tapBloodyUrineRedFlagTile(tester, router, redFlagBadge);

    expect(find.text(t('session.doctor.detail.redFlagTitle')), findsOneWidget,
        reason: 'session detail 沒顯示紅旗卡片');
    expect(find.text('睪丸劇痛'), findsAtLeast(1), reason: 'session.redFlagReason「睪丸劇痛」沒有顯示出來');

    // 狀態徽章顯示翻譯文字（zh-TW 為「紅旗中止」），不是原始 i18n key。
    // 迴歸背景：status_badge.dart 的 key 曾經少了 `common.` namespace 前綴（寫成
    // `patient.home.statusXxx`）。lib/core/i18n/loc.dart 的 t() 用 key 的第一個 dot
    // 段落當 namespace，而 lib/core/router/lng.dart 的 allNamespaces 裡沒有 `patient`，
    // 所以全 app、全五語系、每一種場次狀態的徽章都直接印出 raw key 字串。
    expect(find.text(t('common.patient.home.statusAbortedRedFlag')), findsOneWidget,
        reason: 'AppBar 狀態徽章應該顯示「紅旗中止」的翻譯文字');
    expect(find.text('patient.home.statusAbortedRedFlag'), findsNothing,
        reason: 'StatusBadge 印出了原始 i18n key —— common. namespace 前綴又掉了');
    // 逐字稿也要有內容（不是空場次）。
    expect(find.textContaining('陰囊腫起來'), findsAtLeast(1), reason: '紅旗場次的逐字稿沒有載出病患描述');

    await _ensureAssignedToMe(tester);

    // 迴歸背景（已修）：SessionDetailPage._load() 曾經只在 session.status=='completed' 時才
    // 去查 SOAP report 狀態，aborted_red_flag 場次即使 SOAP 已生成 _reportStatus 也永遠是 null，
    // 「查看報告」按鈕不會出現在這一頁；醫師只能繞到 Reports 列表頁。aborted_red_flag 與
    // completed 同為「會派 SOAP」的終態，兩者都要查（cancelled 不派 SOAP 故不查）。
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.text(t('session.doctor.detail.viewReport')).evaluate().isNotEmpty);
    expect(find.text(t('session.doctor.detail.viewReport')), findsOneWidget,
        reason: 'aborted_red_flag 場次已生成 SOAP，session detail 應該要能直接開「查看報告」'
            '（若這裡失敗：確認 _load() 的 status 條件是否又縮回只剩 completed）');

    // ── Dashboard：統計數字非空（兩場種子場次都已認領給登入的醫師）─
    router.go(prefixLngToPath('/dashboard', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();

    final totalSessionsHint = t('common.doctor.dashboard.monthlyTotalHint');
    final redFlagHint = t('common.doctor.dashboard.redFlagMetricHint');
    final totalSessionsText = _valueBeforeText(tester, totalSessionsHint);
    final redFlagText = _valueBeforeText(tester, redFlagHint);
    expect(totalSessionsText, isNotNull, reason: 'dashboard 找不到本月場次數卡片');
    expect(int.tryParse(totalSessionsText!), isNotNull, reason: '本月場次數不是數字：$totalSessionsText');
    expect(int.parse(totalSessionsText), greaterThanOrEqualTo(2),
        reason: '剛認領了兩場種子場次（血尿 completed + aborted_red_flag），dashboard 卻回報 $totalSessionsText');
    expect(redFlagText, isNotNull, reason: 'dashboard 找不到紅旗警示數卡片');
    expect(int.parse(redFlagText!), greaterThanOrEqualTo(1),
        reason: '認領的場次裡應至少有一筆紅旗警示（睪丸劇痛），dashboard 卻回報 $redFlagText');

    // ── Alerts 頁：critical 紅旗 → 開 detail → 確認處置 ──────
    router.go(prefixLngToPath('/alerts', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(AlertListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();

    // DB 可能不只一筆 critical 紅旗標題是「睪丸劇痛」（同一批「血尿」紅旗種子資料若被重複
    // 灌過，見檔頭 P3 走查註解），所以這裡不假設剛好一筆，`.first` 挑哪一筆都行——真正要
    // 唯一鎖定的是「等一下 acknowledge 的那一筆」，見下面用 `AlertDetailPage.alertId` 直接
    // 拿 route id，不再用（會撞名的）標題文字去反查後端。
    final alertsDebugTexts = tester.widgetList<Text>(find.byType(Text)).map((w) => w.data).toList();
    expect(find.text('睪丸劇痛'), findsAtLeast(1),
        reason: 'alerts 列表沒看到 critical 紅旗「睪丸劇痛」。目前畫面文字：$alertsDebugTexts');
    expect(find.text('CRITICAL'), findsAtLeast(1), reason: 'alerts 列表沒有 CRITICAL 嚴重度標籤');

    await tester.tap(find.text('睪丸劇痛').first, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(AlertDetailPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    // 直接從已經 mount 的 widget 拿 route 帶進來的 alertId——這是「我們剛剛實際點進去、等一下
    // 要 acknowledge 的那一筆」唯一且不會撞名的識別碼，比用標題文字去反查後端列表可靠
    // （標題文字在 DB 有多筆「睪丸劇痛」時不是唯一鍵，見上面註解）。
    final targetAlertId = tester.widget<AlertDetailPage>(find.byType(AlertDetailPage)).alertId;

    expect(find.textContaining('陰囊腫起來'), findsAtLeast(1), reason: 'alert detail 沒有顯示 triggerReason 內容');

    final alreadyAcked = find.text(t('dashboard.alert.detail.acknowledgedHeading')).evaluate().isNotEmpty;
    if (!alreadyAcked) {
      final ackFields = find.byType(TextField);
      expect(ackFields, findsNWidgets(2), reason: 'alert detail 的確認處置表單應有處置說明 + 備註兩個欄位');
      await _typeInto(tester, ackFields.at(0), 'E2E 走查：已告知現場醫護立即安排診療');
      await _typeInto(tester, ackFields.at(1), 'flutter integration test 自動確認處置');
      await tester.tap(find.text(t('dashboard.alert.detail.acknowledgeButton')));
      await _pumpFor(tester, const Duration(seconds: 10),
          until: () => find.text(t('dashboard.alert.detail.acknowledgedHeading')).evaluate().isNotEmpty);
      await tester.pumpAndSettle();
    }
    expect(find.text(t('dashboard.alert.detail.acknowledgedHeading')), findsOneWidget,
        reason: '確認處置後應該顯示「已處置」區塊');

    // ── 不只信 UI：直接重新打 API 驗證後端真的持久化了 ──────
    // UI 顯示「已處置」只代表 AlertDetailPage 的本地 state 被 setState 過；不足以證明
    // acknowledge 真的寫進了 DB（例如伺服器端 commit 失敗但回應仍是 200、或某個中間層
    // 沒把值傳到底）。這裡用完全獨立、繞過該頁 local state 的新 GET 請求重新確認——用上面
    // 從 route 拿到的 `targetAlertId` 精確點名（不用標題文字去 `list()` 裡反查：DB 若有
    // 多筆同標題「睪丸劇痛」的紅旗警示，`.first` 挑到的不保證是這次真的 acknowledge 的
    // 那一筆，曾經因此在 iOS 走查炸過——單筆 GET 用 id 沒有這個歧義）。
    final freshAlert = await AlertsApi().get(targetAlertId);
    expect(freshAlert.acknowledged, isTrue,
        reason: '用獨立的 AlertsApi().get($targetAlertId) 重新查，這筆紅旗警示的 acknowledgedAt 仍是 '
            'null——UI 顯示「已處置」，但後端其實沒有真的持久化這次確認處置（DB 佐證另外用 psql 查'
            'red_flag_alerts.acknowledged_by / acknowledged_at 核對）');
    expect(freshAlert.acknowledgedBy, isNotNull,
        reason: 'acknowledgedBy 沒有寫入是誰確認的');

    // ── Reports 頁：開紅旗場次的 SOAP 報告 ───────────────────
    router.go(prefixLngToPath('/reports', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(ReportListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();

    // 契約修好之後（後端 Decimal 一律輸出 JSON number），Reports 列表要真的有資料，且能開到
    // SOAP 報告內容與逐字稿分頁——這段就是原本被「已知缺陷」分支繞過的完整驗證路徑。
    // 缺陷時期這裡是 `expect(emptyTitle, findsOneWidget)`：report_list_page.dart 的
    // `catch (_) { setState(() => _loading = false); }` 把解析例外吞掉，_reports 停在空陣列，
    // DB 明明有報告，列表頁卻是空狀態。現在反過來鎖住「空狀態不該出現」。
    expect(find.text(t('dashboard.reportList.emptyTitle')), findsNothing,
        reason: 'Reports 列表顯示空狀態——DB 裡有已生成的報告，列表卻是空的，'
            '典型症狀就是整批 SoapReport.fromJson 解析失敗被吞掉');
    final reportRedFlagBadge = t('dashboard.reportList.redFlagBadge');
    expect(find.text(reportRedFlagBadge), findsAtLeast(1),
        reason: 'Reports 列表沒有紅旗徽章的那一列（aborted_red_flag 場次的報告）');
    await _openTesticularRedFlagReport(tester, router, reportRedFlagBadge);

    // 紅旗橫幅 + S/O/A/P 四個內容區塊都要出現。
    expect(find.text(t('soap.redFlag.title')), findsOneWidget, reason: 'SOAP 報告頁沒顯示紅旗橫幅');
    expect(find.textContaining('睪丸劇痛'), findsAtLeast(1), reason: '紅旗橫幅內容沒有帶到「睪丸劇痛」');
    for (final key in [
      'soap.section.subjective.title',
      'soap.section.objective.title',
      'soap.section.assessment.title',
      'soap.section.plan.title',
    ]) {
      expect(find.text(t(key)), findsOneWidget, reason: 'SOAP 報告缺少區塊：$key');
    }
    expect(find.text(t('soap.page.noSummary')), findsNothing, reason: 'SOAP 報告的臨床摘要是空的');

    // 逐字稿分頁。
    await tester.tap(find.text(t('soap.tabs.transcript')));
    await tester.pumpAndSettle();
    expect(find.textContaining('睪丸突然劇烈疼痛'), findsAtLeast(1), reason: '逐字稿分頁沒有載出病患的原始描述');

    // ── 對照：一般（無紅旗）場次的 SOAP 報告也要能正常開 ─────
    router.go(prefixLngToPath('/reports', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(ReportListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();
    // 找一列「沒有」紅旗徽章的報告列（用 Card 逐一檢查，避開已驗證過的紅旗那列）。
    final allReportCards = find.byType(Card);
    Finder? plainReportInkWell;
    for (var i = 0; i < allReportCards.evaluate().length; i++) {
      final card = allReportCards.at(i);
      final hasBadge = find.descendant(of: card, matching: find.text(reportRedFlagBadge)).evaluate().isNotEmpty;
      if (!hasBadge) {
        final inkWell = find.descendant(of: card, matching: find.byType(InkWell));
        if (inkWell.evaluate().isNotEmpty) {
          plainReportInkWell = inkWell.first;
          break;
        }
      }
    }
    expect(plainReportInkWell, isNotNull,
        reason: '找不到一般（無紅旗）場次的報告列，種子資料應該有 completed 血尿場次的 SOAP');
    await tester.tap(plainReportInkWell!, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SoapReportPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    expect(find.text(t('soap.redFlag.title')), findsNothing, reason: '無紅旗場次的 SOAP 報告不該顯示紅旗橫幅');
    for (final key in [
      'soap.section.subjective.title',
      'soap.section.objective.title',
      'soap.section.assessment.title',
      'soap.section.plan.title',
    ]) {
      expect(find.text(t(key)), findsOneWidget, reason: '無紅旗場次的 SOAP 報告缺少區塊：$key');
    }
  }, timeout: const Timeout(Duration(minutes: 6)));
}
