// 產品介紹影片的**驅動腳本**（2026-09-09）。
//
// 這支不是測試，是「導播」：它在 iOS 模擬器上把病患端 → 醫師端的主線走一遍，
// 全程由 `xcrun simctl io booted recordVideo` 錄成畫面，之後剪成約 60 秒的介紹片。
// 目標順序因此和其他 integration_test 完全相反：
//
//   1. **節奏 > 覆蓋率**。每一步之間刻意停 1.2–2 秒（`beat()`），捲動一律用
//      `flingFrom` 的慣性動畫（`swipe()`）而不是 `jumpTo`／瞬移，讓錄出來的畫面
//      是人看得懂的速度，不是機器的速度。
//   2. **斷言只留「我到了那一頁嗎」那一層**。完全不斷言等於在錄一支可能跑錯頁、
//      剪的人事後才發現的廢片；但也不驗業務規則（那是 doctor_walkthrough_test.dart
//      與 patient_text_flow_test.dart 的工作，別在這裡重複）。
//   3. **不動 `tester.view`**。其他走查會把 physicalSize 改成大畫布，好讓 off-screen
//      widget 點得到；這支不行——改了畫布，錄下來的畫面就不是 iPhone 該有的比例。
//      代價是每個 off-screen 目標都得先真的捲到它（`scrollTo()`），而那正好也是
//      影片要拍的東西。
//
// ⚠️ **一律打本機後端**。正式環境（gu-voice-app-production）會建出真場次、對真
// 手機發推播——這支會建場次、跑真 LLM、觸發站內通知，絕不可以指向它。
//
// ── 完整跑法 ────────────────────────────────────────────────────────────────
//
// 前提（缺一不可）：
//   * `docker compose up -d postgres redis`
//   * backend：`cd backend && ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`
//     （JWT_ALGORITHM=HS256、JWT_SECRET_KEY=40 字以上、
//      DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/gu_voice、
//      REDIS_URL=redis://127.0.0.1:6379/0、OPENAI_API_KEY 讀 backend/.env）
//   * **Celery worker**：`cd backend && ./venv/bin/celery -A app.tasks.celery_app worker -l info`
//     SOAP 生成走 Celery（conversation_handler._generate_soap_report_async 只建
//     GENERATING row 再 `.delay()`）。沒有 worker，第 6 步的「SOAP 報告已生成」
//     通知永遠不會出現，第 7 步的快速開單頁就沒有 AI 建議檢查可勾——影片會停在
//     通知中心乾等。
//   * 病患帳號（一般 `/auth/register` 即可）與醫師帳號（`/auth/register` 一律建成
//     patient，要直接改 DB：`update users set role='doctor', department='泌尿科'
//     where email=...`）。醫師的 `name` 就是 DEMO_DOCTOR_NAME 要對上的字串。
//   * 模擬器：**每一次跑之前都要 shutdown 再 boot**，並預先授權麥克風：
//
//       xcrun simctl shutdown "iPhone 17 Pro"; xcrun simctl boot "iPhone 17 Pro"
//       xcrun simctl privacy booted grant microphone com.guvoice.guVoice
//
//     - 授權要先給：不然第一次進問診頁會彈系統權限對話框，它會入鏡（影片毀了），
//       而且沒有人按它，`record` 的 `hasPermission()` 會一直等下去。
//     - **重開機不是保險起見，是必要條件**（2026-09-09 實測，兩次都一樣）：同一顆
//       開著的模擬器連跑兩次，**第二次一定卡在 openMic**——backend log 裡連一次
//       WebSocket 握手都沒有。原因在 `ios/Runner/MicProbe.swift`：它會建一顆
//       AVAudioEngine 讀 inputFormat，而上一輪的 app 被測試框架殺掉時 audio session
//       沒收乾淨，下一輪那顆 engine 就卡住；`conversation_controller.start()` 是
//       「openMic 之後才 `_ws.connect`」，所以 WS 也跟著永遠不連。這一步發生在
//       Dart 有機會做任何事之前，腳本裡沒有任何補救可寫。
//
// 錄影（另開一個 terminal，跑測試前先按下）：
//   xcrun simctl io booted recordVideo --codec=h264 demo.mp4
//
// 測試本體：
//   cd flutter_app && fvm flutter test integration_test/demo_walkthrough_test.dart \
//     -d 6379C9B7-44A5-4226-9FA8-C3F94D627842 \
//     --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
//     --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws \
//     --dart-define=KIOSK_EMAIL=demo.patient@example.com \
//     --dart-define=KIOSK_PASSWORD=Demo1234 \
//     --dart-define=DEMO_DOCTOR_EMAIL=demo.doctor@example.com \
//     --dart-define=DEMO_DOCTOR_PASSWORD=Demo1234 \
//     --dart-define=DEMO_DOCTOR_NAME=林醫師
//
// （`-d <udid>` 換成 `xcrun simctl list devices | grep Booted` 看到的那一顆。）
//
// 為什麼是 KIOSK_EMAIL 而不是 E2E_PATIENT_EMAIL：登入頁的「開始語音問診」大鈕在
// 沒帶 KIOSK_* 時是編譯期死碼（env.dart），而那顆鈕就是第 1 個 beat 要拍的東西。
// 醫師憑證則刻意用 **DEMO_**_ 前綴而不是 E2E_DOCTOR_*：後者會讓登入頁多長出一顆
// 「帶入醫師帳密」的測試鈕（Key('fill-doctor-credentials')），入鏡很醜。
//
// ── 每個 beat 的用意 ────────────────────────────────────────────────────────
//
//   B1  登入頁          品牌與雙入口：kiosk 病患一顆大鈕、醫師走帳密。停 2s。
//   B2  選主訴          「病患自己選，不用打字」——點「血尿」，卡片亮邊框。
//   B3  基本資料 · 選醫師 本輪產品重點之一：問診當下就指定負責醫師，報告與通知
//                       之後才有人收。下拉選單開闔停最久（2.2s + 1.8s）。
//   B4  基本資料 · 其餘  姓名／性別／生日，快速帶過（不是賣點，但要證明是真表單）。
//   B5  問診頁          真 LLM：送 3 句、等 AI 追問。這段最不可控，剪片時通常只留
//                       「病患打字 → AI 回覆浮現」各一次。主訴選「血尿」時規則層會
//                       判出 high 紅旗，畫面上會多一條紅旗橫幅——那是產品功能，
//                       不是腳本出錯，剪片時值得留一格。
//   B6  結束問診 → 完成頁 「問診到此結束」的收尾畫面（8 秒後會自動回首頁，所以這裡
//                       的停留刻意 < 8s，接著主動按「返回首頁」把節奏拿回來）。
//   B7  登出 → 醫師登入   換端。這是影片的分場點。
//   B8  通知中心        「問診完成」「SOAP 報告已生成」兩則——證明醫師是被通知的，
//                       不是自己去翻列表。等 report_ready 可能要 1–2 分鐘（Celery
//                       跑真 LLM），剪片時整段等待剪掉。
//   B9  快速開單頁      **本輪新功能，停最久（每個動作 1.6–2.2s）**：摘要 → AI 建議
//                       檢查 → 勾 2 項 → 備註 → 確認送出 → 成功提示。
//   B10 SOAP 報告頁     「要看全貌也還在」——逐段捲一遍收尾。頁面本身的順序是
//                       **評估 → 計畫 → 主觀 → 客觀**（結論在前，見 _soapSections）。
//
// 影片時長：實測整支 walkthrough 2 分 10 秒上下（兩次分別是 2:08 與 2:22；另加約
// 15 秒 Xcode build＋install，
// 那段模擬器是空桌面，靠 DEMO_MARK_START 剪掉）。本機 gpt-5.6-terra 很快，一輪 LLM
// 只要幾秒、SOAP 生成約 25 秒。「有畫面在動」的素材約 70–90 秒，剪成 60 秒剛好。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/config/env.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/auth/login_page.dart';
import 'package:gu_voice/features/doctor/screens/notification_page.dart';
import 'package:gu_voice/features/doctor/screens/quick_orders_page.dart';
import 'package:gu_voice/features/doctor/screens/soap_report_page.dart';
import 'package:gu_voice/features/patient/medical_info_page.dart';
import 'package:gu_voice/features/patient/patient_home_page.dart';
import 'package:gu_voice/features/patient/select_complaint_page.dart';
import 'package:gu_voice/features/patient/session_thank_you_page.dart';
import 'package:gu_voice/features/voice/screens/conversation_page.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';

const _doctorEmail = String.fromEnvironment('DEMO_DOCTOR_EMAIL');
const _doctorPassword = String.fromEnvironment('DEMO_DOCTOR_PASSWORD');

/// 下拉選單裡要挑的醫師顯示名稱。用「名字」而不是 uuid：同一支腳本在任何環境
/// 只要有一位同名醫師就跑得動，換環境不必改 code（其他走查的同一條原則）。
const _doctorName = String.fromEnvironment('DEMO_DOCTOR_NAME', defaultValue: '林醫師');

/// 影片裡會出現在畫面上的病患姓名。**刻意是假名並自帶「測試資料」字樣**——
/// 這支會把畫面錄下來對外播放，真實病患姓名絕不能入鏡。
const _patientName = '示範病患（測試資料）';

/// 病患在問診頁要打的台詞。兩句剛好夠 AI 追問一輪，第三句留給節奏（太多輪影片會拖）。
const _lines = [
  '大概三天前開始，白天小便的次數變多，一天大概十幾次。',
  '排尿的時候不會痛，也沒有發燒，尿的顏色看起來正常。',
  '晚上會起來上兩三次廁所，平常喝水量沒有變。',
];

// ── 導播用的 helper ─────────────────────────────────────────────────────────

/// 有界的 `pumpAndSettle`。
///
/// ⚠️ 這支腳本最貴的一次失誤：裸 `pumpAndSettle()` 的預設 timeout 是 **10 分鐘**，
/// 而問診頁上有永遠不會停的動畫（錄音脈動／AI 回應中的指示器）。第一次真跑就卡在
/// 「送出基本資料 → 進問診頁」那一下，10 分 51 秒後以 `pumpAndSettle timed out`
/// 收場。整支腳本因此一律走這裡：settle 不下來是那些頁面的**正常狀態**，不是錯誤，
/// 逾時就繼續往下走。（doctor_walkthrough_test.dart 用固定 `_pumpFor` 迴圈避開同一
/// 個坑；這支要的是「盡快安定、安定不了就算了」，所以改成有界 settle。）
Future<void> settle(
  WidgetTester tester, {
  Duration timeout = const Duration(milliseconds: 1200),
}) async {
  try {
    await tester.pumpAndSettle(
      const Duration(milliseconds: 80),
      EnginePhase.sendSemanticsUpdate,
      timeout,
    );
  } on FlutterError {
    // 頁面上有停不下來的動畫。畫面已經在動了，這正是要錄的東西。
  }
}

/// 一個「節拍」：先讓畫面安定，再**用真實時間**停住讓觀眾看清楚，最後再安定一次。
///
/// 為什麼是 `DateTime.now()` 迴圈而不是 `Future.delayed`：integration_test 的
/// binding 是 live 的，`pump()` 會真的送一幀出去；用牆鐘控迴圈可以同時保證
/// (a) 真的過了這麼多毫秒、(b) 這段期間畫面持續在重繪（進行中的動畫不會凍住）。
Future<void> beat(WidgetTester tester, {int ms = 1200}) async {
  await settle(tester, timeout: const Duration(milliseconds: 900));
  final until = DateTime.now().add(Duration(milliseconds: ms));
  while (DateTime.now().isBefore(until)) {
    await tester.pump(const Duration(milliseconds: 16));
  }
}

/// 等一個條件成立（真 LLM／SOAP 生成用），期間持續 pump 讓畫面活著。
/// 逾時**不 fail**，由呼叫端自己用 `expect` 說出「到底是哪一頁沒到」——
/// 那樣的失敗訊息剪片的人看得懂，`waitFor timeout` 看不懂。
Future<bool> waitFor(
  WidgetTester tester,
  bool Function() ready, {
  Duration timeout = const Duration(seconds: 30),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    if (ready()) return true;
    await tester.pump(const Duration(milliseconds: 100));
  }
  return ready();
}

Size _screen(WidgetTester tester) =>
    tester.view.physicalSize / tester.view.devicePixelRatio;

/// 這一頁真正在捲的那個 Scrollable。
///
/// 為什麼不能用 `find.byType(Scrollable).first`：SOAP 報告頁的 body 是 TabBarView，
/// 而 TabBarView 本身就是一個（水平的）Scrollable，在 tree 裡排在內層 ListView 前面。
/// 拿 `.first` 去捲＝橫向換頁。
///
/// 兩段式解析：
///   1. 目標已經 build 出來時，取**它自己的**垂直 Scrollable 祖先——分頁版面裡
///      「報告」與「逐字稿」兩個 ListView 尺寸一樣大，猜錯就會捲到看不見的那一頁。
///   2. 目標還沒 build（lazy ListView 的下半段），退回「所有垂直 Scrollable 裡視窗
///      最大的那個」。單一 ListView 的頁面兩條路結果相同。
ScrollableState? _verticalScrollable(WidgetTester tester, {Finder? of}) {
  ScrollableState? pick(Finder f) {
    ScrollableState? best;
    for (final element in f.evaluate()) {
      final state = (element as StatefulElement).state as ScrollableState;
      final pos = state.position;
      if (pos.axis != Axis.vertical || !pos.hasViewportDimension) continue;
      if (best == null || pos.viewportDimension > best.position.viewportDimension) {
        best = state;
      }
    }
    return best;
  }

  if (of != null && of.evaluate().isNotEmpty) {
    final owner = pick(find.ancestor(of: of, matching: find.byType(Scrollable)));
    if (owner != null) return owner;
  }
  return pick(find.byType(Scrollable));
}

/// 平滑捲動一段。
///
/// 手勢優先用 `flingFrom`：甩一下放開，後續的慣性動畫是引擎自己跑的，錄起來就是
/// 「手指滑過去」該有的減速曲線；`jumpTo` 或單步 `drag` 是瞬移，影片上像掉幀。
/// 起點取畫面 70% 高：避開 AppBar，也避開底部的動作列與安全區。
///
/// ⚠️ 手勢會不會被捲動區收下，取決於那個座標底下是什麼。實測在基本資料頁，
/// 起點壓在輸入框／快速新增晶片上時，`timedDragFrom` 整整 24 次一格都沒捲動
/// （診斷訊息顯示畫面文字完全沒變）。所以這裡加一道保險：手勢後若 scroll offset
/// 沒動，就直接對 ScrollPosition 開 `animateTo`。錄出來一樣是等速滑動，不會讓
/// 某一頁的版面卡死整支影片。
Future<void> swipe(
  WidgetTester tester, {
  double dy = -240,
  double speed = 900,
  Finder? towards,
}) async {
  final size = _screen(tester);
  final before = _verticalScrollable(tester, of: towards)?.position.pixels;
  await tester.flingFrom(
    Offset(size.width / 2, size.height * 0.70),
    Offset(0, dy),
    speed,
  );
  await settle(tester);

  final state = _verticalScrollable(tester, of: towards);
  if (state == null || before == null) return;
  final pos = state.position;
  if ((pos.pixels - before).abs() > 1) return; // 手勢生效，收工。
  final target = (pos.pixels - dy).clamp(pos.minScrollExtent, pos.maxScrollExtent);
  if ((target - pos.pixels).abs() < 1) return; // 已經到頂／到底，不是手勢的問題。
  final done = pos.animateTo(
    target,
    duration: const Duration(milliseconds: 420),
    curve: Curves.easeInOut,
  );
  await settle(tester);
  await done;
}

/// 目標是否**真的在畫面上**（不只是「在 widget tree 裡」）。
///
/// `dragUntilVisible` / `scrollUntilVisible` 判的是 `finder.evaluate().isNotEmpty`，
/// 對 cacheExtent 內已經 build 但還在畫面外的 widget 會直接回報成功，於是後面的
/// `tap()` 打在螢幕外、或根本沒捲動——影片就少了那一段捲動。這裡改判 render box
/// 的實際螢幕座標。
///
/// ⚠️ 判的是**中心點**而不是整個 rect 落在安全範圍內。第一版用後者，結果卡在
/// 選症狀頁的「下一步」——那顆鈕在 SafeArea 底欄裡（不在捲動區內），本來就貼著
/// 螢幕下緣，`rect.bottom <= height-56` 永遠不成立，於是 scrollTo 把整個清單捲
/// 到底 24 次後 fail。底欄按鈕在畫面上、按得到、也拍得到，就該算數。
bool _onScreen(WidgetTester tester, Finder f) {
  final elements = f.evaluate();
  if (elements.isEmpty) return false;
  final ro = elements.first.renderObject;
  if (ro is! RenderBox || !ro.attached || !ro.hasSize) return false;
  final rect = ro.localToGlobal(Offset.zero) & ro.size;
  final size = _screen(tester);
  final c = rect.center;
  // 上緣留 AppBar 的高度：被標題列蓋住的東西點得到但看不清楚。
  return c.dy >= 64 && c.dy <= size.height - 16 && c.dx >= 0 && c.dx <= size.width;
}

/// 一路平滑捲到目標露臉為止。找不到就 fail，並說清楚是在找什麼——
/// 這是這支腳本唯一會「主動放棄」的地方。
Future<void> scrollTo(
  WidgetTester tester,
  Finder target, {
  String? what,
  double step = -200,
  int max = 24,
}) async {
  for (var i = 0; i < max; i++) {
    if (_onScreen(tester, target)) return;
    await swipe(tester, dy: step, speed: 700, towards: target);
  }
  if (_onScreen(tester, target)) return;
  // 失敗訊息附上「現在畫面上有哪些字」與捲動位置。導播腳本失敗時最想知道的是
  // 「那它停在哪一頁、到底有沒有在捲」，光看 finder 的描述看不出來。
  final texts = tester
      .widgetList<Text>(find.byType(Text))
      .map((w) => w.data)
      .whereType<String>()
      .take(40)
      .toList();
  final pos = _verticalScrollable(tester, of: target)?.position;
  fail('捲了 $max 次仍看不到「${what ?? target.describeMatch(Plurality.one)}」'
      '（tree 裡命中 ${target.evaluate().length} 個；'
      'scroll=${pos?.pixels.toStringAsFixed(0)}/${pos?.maxScrollExtent.toStringAsFixed(0)}）'
      '——版面改過或資料沒載出來，錄下去會是一支跑錯頁的影片。目前畫面文字：$texts');
}

/// 捲到看得見再點，中間夾一個節拍：觀眾先看到目標，才看到它被按下。
Future<void> revealAndTap(
  WidgetTester tester,
  Finder target, {
  String? what,
  int hold = 900,
}) async {
  await scrollTo(tester, target, what: what);
  await beat(tester, ms: hold);
  await tester.tap(target, warnIfMissed: false);
  await settle(tester);
}

/// 點下去，直到某件事真的發生為止（最多 [tries] 次）。
///
/// ⚠️ 為什麼需要重試：實測在「登出 → 醫師登入」那一步，對 `Key('login-submit')`
/// 的第一次 tap 有機會落空——flutter_test 印出
/// `derived an Offset (201.0, 539.0) that would not hit test on the specified widget`，
/// hit test 只打到 Scaffold 的 Material，`authProvider.error` 停在 null（＝根本沒送出
/// 登入請求）。成因是打完密碼後鍵盤／焦點造成的版面位移還沒穩定，widget 的 render box
/// 座標與實際可點區域短暫對不上。與其賭一次，不如「按了沒反應就再按一次」——這也是
/// 真人在那台 iPad 上會做的事，錄進影片裡也不突兀。
Future<bool> tapUntil(
  WidgetTester tester,
  Finder target,
  bool Function() done, {
  int tries = 3,
  Duration each = const Duration(seconds: 12),
}) async {
  for (var attempt = 0; attempt < tries; attempt++) {
    if (done()) return true;
    if (target.evaluate().isEmpty) return done();
    await tester.tap(target, warnIfMissed: false);
    if (await waitFor(tester, done, timeout: each)) return true;
    await beat(tester, ms: 600);
  }
  return done();
}

/// 打字。先 tap 再 enterText 是 patient_text_flow_test 踩過的坑（合成 tap 不等於
/// 真實 focus，第二次起會靜默不送出）；這裡照抄那個保險做法。
Future<void> typeInto(WidgetTester tester, Finder field, String text) async {
  await tester.tap(field, warnIfMissed: false);
  await tester.pump();
  await tester.enterText(field, text);
  await settle(tester);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('demo walkthrough：病患問診 → 醫師快速開單 → SOAP 報告', (tester) async {
    expect(
      Env.hasKioskCredentials,
      isTrue,
      reason: '沒帶 --dart-define=KIOSK_EMAIL/KIOSK_PASSWORD：登入頁的「開始語音問診」'
          '大鈕在編譯期就是死碼，第一個鏡頭會是空的。'
          '（用 tool/record_demo.sh 錄影時，這五個 define 要一起傳進去：'
          'KIOSK_EMAIL / KIOSK_PASSWORD / DEMO_DOCTOR_EMAIL / DEMO_DOCTOR_PASSWORD / '
          'DEMO_DOCTOR_NAME）',
    );
    expect(
      _doctorEmail.isNotEmpty && _doctorPassword.isNotEmpty,
      isTrue,
      reason: '沒帶 --dart-define=DEMO_DOCTOR_EMAIL/DEMO_DOCTOR_PASSWORD：走不到醫師端',
    );
    // 刻意不設 tester.view.physicalSize：錄影要的是這台模擬器原生的畫面比例。

    ApiClient.instance.init();
    await Locales.loadAll();
    await TokenStore.instance.clear();

    final container = ProviderContainer();
    addTearDown(container.dispose);
    ApiClient.instance.onAuthCleared =
        () => container.read(authProvider.notifier).forceLoggedOut();
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const App()),
    );
    await settle(tester);

    // 剪片對時錨點。`tool/record_demo.sh` 是「先開錄影、再跑這支測試」，中間
    // 隔著 Xcode build＋install 的幾十秒空桌面。那支腳本約定從 log 裡撈
    // `DEMO_MARK_START <epoch 秒>` 當 --trim-start 的依據，所以這一行要印在
    // 「第一幀真的畫面出現」的當下——早一點會把 build 的空畫面剪進去，
    // 晚一點會切掉片頭。格式不能改（record_demo.sh 用 regex 撈這個數字）。
    debugPrint('DEMO_MARK_START ${DateTime.now().millisecondsSinceEpoch / 1000.0}');

    // ── B1 登入頁 ─────────────────────────────────────────────────────────
    // 開場鏡頭：一顆病患大鈕、一組醫師帳密。停久一點，這是片頭。
    expect(find.byType(LoginPage), findsOneWidget, reason: '沒停在登入頁');
    final kioskButton = find.text(t('common.login.kioskStart'));
    expect(kioskButton, findsOneWidget,
        reason: '登入頁沒有「開始語音問診」大鈕（KIOSK_* define 沒生效？）');
    await beat(tester, ms: 2000);

    // 按下＝以 kiosk 專用 patient 帳號登入並直接進選症狀頁（產品行為，不是測試捷徑）。
    final loggedIn = await tapUntil(
      tester,
      kioskButton,
      () => container.read(authProvider).user != null,
      each: const Duration(seconds: 20),
    );
    expect(loggedIn, isTrue,
        reason: 'kiosk 登入失敗（${container.read(authProvider).error}）——'
            '確認 KIOSK_EMAIL 這個帳號在本機 DB 存在且是 patient');

    // ── B2 選主訴 ─────────────────────────────────────────────────────────
    final onComplaints = await waitFor(
      tester,
      () => find.byType(SelectComplaintPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 20),
    );
    expect(onComplaints, isTrue, reason: 'kiosk 登入後沒有直接進到選症狀頁');
    await waitFor(
      tester,
      () => find.byType(ListTile).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 20),
    );
    await beat(tester, ms: 1600);

    // 用主訴文字挑，不用 index：清單順序由後端 display_order 決定，會變。
    const complaint = '血尿';
    final complaintTile = find.ancestor(
      of: find.text(complaint),
      matching: find.byType(ListTile),
    );
    await revealAndTap(tester, complaintTile, what: '主訴「$complaint」', hold: 800);
    // 選中後卡片會亮出 primary 邊框 + 序號圓點——讓觀眾看到「選到了」再往下。
    await beat(tester, ms: 1400);

    await revealAndTap(
      tester,
      find.widgetWithText(FilledButton, t('intake.selectComplaint.ctaCount', args: {'count': 1})),
      what: '「下一步：填寫病史」',
      hold: 700,
    );

    // ── B3 基本資料 · 選醫師（產品重點，停最久）─────────────────────────────
    final onIntake = await waitFor(
      tester,
      () => find.byType(MedicalInfoPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 15),
    );
    expect(onIntake, isTrue, reason: '沒有進到基本資料頁');
    // 醫師清單是 API 來的（SessionsApi().getDoctors()）；等它載完再開選單，
    // 否則錄到的是一顆轉圈圈的下拉。
    await waitFor(
      tester,
      () => find.byType(CircularProgressIndicator).evaluate().isEmpty,
      timeout: const Duration(seconds: 20),
    );
    await beat(tester, ms: 1800);

    final doctorField = find.byType(DropdownButtonFormField<String>);
    expect(doctorField, findsOneWidget, reason: '基本資料頁找不到「負責醫師」下拉');
    await revealAndTap(tester, doctorField, what: '負責醫師下拉', hold: 1400);
    // 選單展開的那一刻是這一段的主鏡頭：停 2.2s。
    await beat(tester, ms: 2200);

    // 選單裡每一項是「姓名 · 科別」。用姓名文字挑到 demo 醫師本人——後面的
    // 「問診完成」「SOAP 報告已生成」兩則通知就是寄到這個帳號，第 8 步才有東西看。
    final doctorOption = find.textContaining(_doctorName).last;
    expect(doctorOption, findsOneWidget,
        reason: '醫師下拉裡找不到「$_doctorName」——DEMO_DOCTOR_NAME 要對上 users.name');
    await tester.tap(doctorOption, warnIfMissed: false);
    await settle(tester);
    await beat(tester, ms: 1800);

    // ── B4 基本資料 · 其餘欄位 ─────────────────────────────────────────────
    // `_valid` 要求姓名 + 性別 + 生日 + 醫師四項齊全，缺一顆送出鈕就是 disabled。
    final nameField = find.byType(TextField).first;
    await scrollTo(tester, nameField, what: '姓名欄位');
    await typeInto(tester, nameField, _patientName);
    await beat(tester, ms: 900);

    final genderChip = find.byType(ChoiceChip).first;
    await revealAndTap(tester, genderChip, what: '性別選項', hold: 700);
    await beat(tester, ms: 700);

    // 生日：開系統 date picker，直接確認 initialDate(1980)。
    final dobButton = find.byType(OutlinedButton).first;
    await revealAndTap(tester, dobButton, what: '出生日期', hold: 700);
    await beat(tester, ms: 1200);
    final okButton = find.text('OK');
    await tester.tap(
      okButton.evaluate().isNotEmpty ? okButton : find.byType(TextButton).last,
      warnIfMissed: false,
    );
    await settle(tester);
    await beat(tester, ms: 900);

    // 送出＝建場次（POST /sessions）並進對話頁。
    await revealAndTap(
      tester,
      find.widgetWithText(FilledButton, t('intake.medicalInfo.nav.submit')),
      what: '「開始問診」',
      hold: 900,
    );

    // ── B5 問診頁：文字輸入 × 真 LLM ───────────────────────────────────────
    final onConversation = await waitFor(
      tester,
      () => find.byType(ConversationPage).evaluate().isNotEmpty &&
          container.read(conversationControllerProvider).session != null,
      timeout: const Duration(seconds: 40),
    );
    expect(onConversation, isTrue,
        reason: '沒有進到問診頁——基本資料必填欄位可能沒填滿（送出鈕是 disabled）');

    // 趁 controller 還活著把場次 id 抄下來（離頁後 autoDispose 會把它丟掉，再 read
    // 只會拿到全新的 initial state）。B9 要用它確認「點開的是這一場」——本機 DB 裡
    // 留著前幾次錄影的舊通知，光看標題分不出來。
    final demoSessionId = container.read(conversationControllerProvider).session!.id;

    // ⚠️ 這一步的等待要給得比直覺長。`conversation_controller.start()` 是
    // 「configureSession → openMic →（無論成敗）_ws.connect」的順序，而 openMic
    // 在 iOS 上會叫原生探針 `MicProbe.hasUsableInput`（建一顆 AVAudioEngine 讀
    // inputFormat）。在**沒有麥克風的 Mac**（本專案的錄影機器就是）上那顆探針偶爾
    // 會拖上十幾秒，WS 因此連帶延後——實測 40 秒逾時過一次，重開模擬器後就正常。
    // 這裡放到 90 秒；真的還是連不上多半是模擬器的 audio session 卡住了。
    final wsOpen = await waitFor(
      tester,
      () => container.read(conversationControllerProvider).connection == WsConnState.open,
      timeout: const Duration(seconds: 90),
    );
    expect(wsOpen, isTrue,
        reason: 'WebSocket 沒連上，後面拍不到任何 AI 回覆。若 backend log 裡連一次 '
            'WebSocket 握手都沒有，就是卡在 openMic：把模擬器 shutdown 再 boot 一次'
            '（`xcrun simctl shutdown <udid> && xcrun simctl boot <udid>`）再錄。');

    // 給剪片的人的提醒：錄影機器沒有音訊輸入時，問診頁會多一條「語音功能無法使用」
    // 的橫幅（product 的降級行為，見 conversation_controller.start 的註解——開麥失敗
    // 不擋問診，文字照走）。要拍到乾淨的問診頁，得在有麥克風的 Mac 上錄。
    final voiceUnavailable =
        container.read(conversationControllerProvider).voiceUnavailable;
    if (voiceUnavailable != null) {
      debugPrint('DEMO_NOTE 這台機器沒有可用的麥克風（$voiceUnavailable）——'
          '問診頁會出現「語音功能無法使用」橫幅，剪片時請留意。');
    }

    // 等 AI 開場白落到逐字稿上再開始打字，不然畫面上會是「病患先自言自語」。
    await waitFor(
      tester,
      () => container
          .read(conversationControllerProvider)
          .messages
          .any((m) => m.sender != 'patient'),
      timeout: const Duration(seconds: 60),
    );
    await beat(tester, ms: 1800);

    var sent = 0;
    for (final line in _lines) {
      final state = container.read(conversationControllerProvider);
      if (state.completed) break; // 理論上 normal 情境不會提早結束，防禦而已。
      final before = state.messages.length;

      final input = find.byType(TextField).last;
      expect(input, findsOneWidget, reason: '問診頁找不到文字輸入框');
      await typeInto(tester, input, line);
      // 打完先停一下：影片要讓觀眾讀完這句話再看到它被送出。
      await beat(tester, ms: 1100);
      await tester.tap(find.byIcon(Icons.send), warnIfMissed: false);
      sent++;

      // 真 OpenAI，慢。等 AI 那一則回來（訊息數 +2：自己那則 + AI 那則）。
      await waitFor(
        tester,
        () {
          final s = container.read(conversationControllerProvider);
          return s.completed || s.messages.length > before + 1;
        },
        timeout: const Duration(seconds: 90),
      );
      // AI 回覆逐字浮現的那幾秒本身就是畫面，停久一點。
      await beat(tester, ms: 2000);
    }
    expect(sent, greaterThanOrEqualTo(2),
        reason: '只送出了 $sent 句，影片撐不起「AI 會追問」這件事');

    // ── B6 結束問診 → 完成頁 ───────────────────────────────────────────────
    // AppBar 裡那顆才是「結束問診」（body 裡另有按鈕，用 byType().first 會點錯）。
    final endButton = find.descendant(
      of: find.byType(AppBar),
      matching: find.widgetWithText(TextButton, t('conversation.endSession')),
    );
    expect(endButton, findsOneWidget, reason: '問診頁 AppBar 找不到「結束問診」');
    await beat(tester, ms: 1000);
    await tester.tap(endButton);

    final onThankYou = await waitFor(
      tester,
      () => find.byType(SessionThankYouPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 45),
    );
    expect(onThankYou, isTrue, reason: '按了結束問診沒有導到完成頁');
    // ⚠️ 完成頁 8 秒後會自己跳回首頁（SessionThankYouPage 的 Timer）。停留刻意
    // 壓在 8 秒內，再主動按「返回首頁」，讓轉場是我們決定的、不是計時器決定的。
    await beat(tester, ms: 3000);
    await tester.tap(
      find.widgetWithText(FilledButton, t('session.thankYou.backNowAction')),
      warnIfMissed: false,
    );
    await settle(tester);

    // ── B7 登出 → 以醫師身分登入（分場點）──────────────────────────────────
    final onPatientHome = await waitFor(
      tester,
      () => find.byType(PatientHomePage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 20),
    );
    expect(onPatientHome, isTrue, reason: '沒有回到病患首頁');
    await beat(tester, ms: 1400);

    await tester.tap(find.byIcon(Icons.logout), warnIfMissed: false);
    final backToLogin = await waitFor(
      tester,
      () => find.byType(LoginPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 25),
    );
    expect(backToLogin, isTrue, reason: '登出後沒有回到登入頁');
    await beat(tester, ms: 1600);

    final loginFields = find.byType(TextField);
    expect(loginFields, findsAtLeast(2), reason: '登入頁應有 email / password 兩欄');
    await typeInto(tester, loginFields.at(0), _doctorEmail);
    await beat(tester, ms: 600);
    await typeInto(tester, loginFields.at(1), _doctorPassword);
    // 先收焦點：鍵盤退場後版面才不會在按下去的那一瞬間還在位移（見 tapUntil 的註解），
    // 順帶也讓鏡頭裡的登入頁是完整的，不是被鍵盤切掉一半的。
    FocusManager.instance.primaryFocus?.unfocus();
    await beat(tester, ms: 1200);

    final doctorIn = await tapUntil(
      tester,
      find.byKey(const Key('login-submit')),
      () => container.read(authProvider).user?.isPatient == false,
      each: const Duration(seconds: 15),
    );
    expect(doctorIn, isTrue,
        reason: '醫師登入失敗（${container.read(authProvider).error}）——'
            'DEMO_DOCTOR_EMAIL 這個帳號的 role 有改成 doctor 嗎');

    // ── B8 通知中心 ───────────────────────────────────────────────────────
    // iOS 的醫師落地頁就是通知中心（route_guard.landingPath）；不用自己導。
    final onNotifications = await waitFor(
      tester,
      () => find.byType(NotificationPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 25),
    );
    expect(onNotifications, isTrue, reason: '醫師登入後沒有落在通知中心');

    // 「問診完成」（SESSION_COMPLETE）幾乎是立刻就有。
    const sessionCompleteTitle = '問診完成';
    const reportReadyTitle = 'SOAP 報告已生成';
    final sawSessionComplete = await waitFor(
      tester,
      () => find.text(sessionCompleteTitle).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 60),
    );
    expect(sawSessionComplete, isTrue,
        reason: '通知中心沒有「$sessionCompleteTitle」——這則是寄給場次的負責醫師的，'
            '確認 B3 選到的是 $_doctorName 本人');
    await beat(tester, ms: 1800);

    // 「SOAP 報告已生成」（REPORT_READY）要等 Celery 跑完真 LLM，1–2 分鐘是常態。
    // dashboard WS 的 report_generated 事件會自動觸發 refetch，所以這裡只要等；
    // 萬一 WS 斷了，下面的下拉刷新是備援。剪片時整段等待剪掉。
    var sawReportReady = await waitFor(
      tester,
      () => find.text(reportReadyTitle).evaluate().isNotEmpty,
      timeout: const Duration(minutes: 3),
    );
    if (!sawReportReady) {
      // 備援：下拉刷新（RefreshIndicator）。順帶也是個好看的手勢。
      final size = _screen(tester);
      await tester.timedDragFrom(
        Offset(size.width / 2, size.height * 0.35),
        const Offset(0, 260),
        const Duration(milliseconds: 500),
      );
      await settle(tester);
      sawReportReady = await waitFor(
        tester,
        () => find.text(reportReadyTitle).evaluate().isNotEmpty,
        timeout: const Duration(seconds: 90),
      );
    }
    expect(sawReportReady, isTrue,
        reason: '等不到「$reportReadyTitle」——十之八九是 Celery worker 沒開，'
            'SOAP 生成任務只被 .delay() 進 Redis 就沒人消化了');
    await beat(tester, ms: 2000);

    // ── B9 快速開單頁（本輪新功能，停最久）─────────────────────────────────
    // 點 report_ready 那則 → notification.route() 回 /orders/:sessionId。
    //
    // ⚠️ 不能只點「第一則 report_ready」就當數：本機 DB 留著前幾次錄影的舊通知，
    // 標題一模一樣。清單是新到舊排，所以第一則**遲早**是這一場的，但在新通知落地
    // 之前第一則是舊的那一場——那樣錄出來的快速開單頁講的是別人的病歷。這裡照
    // doctor_walkthrough_test 的做法：點進去驗 `QuickOrdersPage.sessionId`，
    // 不是這一場就回通知中心、等到清單真的多一則再試。
    final reportReadyTile = find.ancestor(
      of: find.text(reportReadyTitle),
      matching: find.byType(ListTile),
    );
    var onQuickOrders = false;
    for (var attempt = 0; attempt < 6 && !onQuickOrders; attempt++) {
      final seen = find.text(reportReadyTitle).evaluate().length;
      await revealAndTap(tester, reportReadyTile.first,
          what: '「$reportReadyTitle」通知', hold: 1600);
      final opened = await waitFor(
        tester,
        () => find.byType(QuickOrdersPage).evaluate().isNotEmpty,
        timeout: const Duration(seconds: 25),
      );
      expect(opened, isTrue, reason: 'report_ready 通知沒有導到快速開單頁');
      final page = tester.widget<QuickOrdersPage>(find.byType(QuickOrdersPage));
      if (page.sessionId == demoSessionId) {
        onQuickOrders = true;
        break;
      }
      // 開到舊場次：回通知中心等新的那一則落地（清單長度變多）再點一次。
      container.read(routerProvider).go(prefixLngToPath('/notifications', currentLng));
      await waitFor(
        tester,
        () => find.byType(NotificationPage).evaluate().isNotEmpty,
        timeout: const Duration(seconds: 20),
      );
      await waitFor(
        tester,
        () => find.text(reportReadyTitle).evaluate().length > seen,
        timeout: const Duration(minutes: 2),
      );
      await beat(tester, ms: 1200);
    }
    expect(onQuickOrders, isTrue,
        reason: '通知中心最上面那則「$reportReadyTitle」始終不是這一場'
            '（session=$demoSessionId）——SOAP 可能生成失敗，看 Celery worker 的 log');
    await waitFor(
      tester,
      () => find.byType(CircularProgressIndicator).evaluate().isEmpty,
      timeout: const Duration(seconds: 30),
    );
    // 摘要卡：醫師點開推播後第一眼看到的東西。
    expect(find.text(t('soap.quickOrders.summaryTitle')), findsOneWidget,
        reason: '快速開單頁沒有「問診摘要」卡');
    await beat(tester, ms: 2200);

    // AI 建議檢查清單。每一項是 CheckboxListTile，key 是 `exam-item-<檢查名>`；
    // 檢查名是 LLM 產的，所以用型別挑、再從 key 認人，不寫死名稱。
    await scrollTo(tester, find.text(t('soap.quickOrders.testsTitle')),
        what: '「AI 建議檢查」卡');
    await beat(tester, ms: 2000);

    final examItems = find.byType(CheckboxListTile);
    expect(examItems, findsAtLeast(1),
        reason: 'AI 這次沒有建議任何檢查——影片的重點動作（勾選）就沒了；'
            '換一個症狀更明確的主訴再錄一次');

    // 刻意「預設一項都不勾」是這一頁的設計（見 quick_orders_page.dart 註解）。
    // 影片要拍的正是醫師自己勾的那兩下。
    final toTick = examItems.evaluate().length >= 2 ? 2 : 1;
    for (var i = 0; i < toTick; i++) {
      final item = find.byType(CheckboxListTile).at(i);
      await revealAndTap(tester, item, what: '第 ${i + 1} 項建議檢查', hold: 1200);
      await beat(tester, ms: 1100);
    }

    // 備註（Key('exam-order-note')）：示範「這張單不只是勾選」。
    final note = find.byKey(const Key('exam-order-note'));
    await scrollTo(tester, note, what: '備註欄');
    await beat(tester, ms: 900);
    await typeInto(tester, note, '請安排門診回診時一併說明結果。');
    await beat(tester, ms: 1600);

    // 送出鈕在 bottomNavigationBar，永遠在畫面上，不需要捲。
    // 走 tapUntil：實測這一下也會印 hit-test miss 警告（底欄在 SafeArea 內，
    // 算出來的中心點偶爾落在安全區的 padding 上），成功提示是 SnackBar，
    // 「有沒有出現」正好是最好的完成判準。
    final submit = find.byKey(const Key('exam-order-submit'));
    expect(submit, findsOneWidget, reason: '快速開單頁找不到「確認送出」');
    await beat(tester, ms: 1000);
    final submitted = await tapUntil(
      tester,
      submit,
      () => find.text(t('soap.quickOrders.submitted')).evaluate().isNotEmpty,
      each: const Duration(seconds: 20),
    );
    expect(submitted, isTrue,
        reason: '沒看到「${t('soap.quickOrders.submitted')}」——送出失敗了'
            '（POST /exam-orders 或本機後端出問題）');
    await beat(tester, ms: 2200);
    // 等 SnackBar 自己退場再往下。它浮在底部，會蓋住頁底那條「查看完整報告」——
    // 沒等就捲下去點，點到的是 SnackBar 不是連結。
    await waitFor(
      tester,
      () => find.byType(SnackBar).evaluate().isEmpty,
      timeout: const Duration(seconds: 10),
    );

    // ── B10 SOAP 報告頁：S/O/A/P 快速捲一遍 ────────────────────────────────
    await revealAndTap(
      tester,
      find.widgetWithText(TextButton, t('soap.quickOrders.viewFullReport')),
      what: '「查看完整報告」',
      hold: 1200,
    );

    final onSoap = await waitFor(
      tester,
      () => find.byType(SoapReportPage).evaluate().isNotEmpty,
      timeout: const Duration(seconds: 25),
    );
    expect(onSoap, isTrue, reason: '沒有導到 SOAP 報告頁');
    await waitFor(
      tester,
      () => find.byType(CircularProgressIndicator).evaluate().isEmpty,
      timeout: const Duration(seconds: 30),
    );
    await beat(tester, ms: 1800);

    // 四段各捲到位停一拍。這裡的 expect 是整支腳本最後一道「我真的在這一頁」的保險：
    // 少了它，錄到的可能是一頁「報告尚未產生」的空狀態。
    //
    // ⚠️ 順序是 **A → P → S → O**，不是 S/O/A/P。`soap_report_page._soapSections`
    // 刻意把「評估／計畫」排在最前面（對齊 web 版：醫師先看結論，再回頭看依據）。
    // 第一版照字母順序寫成 S→O→A→P，跑到「評估」時已經捲過頭到頁尾（診斷訊息：
    // scroll=1654/1654、評估在 tree 裡命中 0 個——lazy ListView 早就把上面那張卡
    // 回收了），24 次都往下捲當然找不到。字卡文案也要照這個順序寫。
    for (final key in const [
      'soap.section.assessment.title',
      'soap.section.plan.title',
      'soap.section.subjective.title',
      'soap.section.objective.title',
    ]) {
      final heading = find.text(t(key));
      // ⚠️ 先捲再斷言，順序不能反：報告頁是 lazy ListView，「評估」「計畫」在
      // offset 0 時根本還沒 build，先 expect 會拿 findsNothing 假性失敗。
      await scrollTo(tester, heading, what: t(key), step: -180);
      expect(heading, findsOneWidget, reason: 'SOAP 報告頁缺少「${t(key)}」段落');
      await beat(tester, ms: 1500);
    }

    // 收尾：慢慢滑到底，鏡頭停住。
    await swipe(tester, dy: -320, speed: 700);
    await beat(tester, ms: 2000);
  }, timeout: const Timeout(Duration(minutes: 20)));
}
