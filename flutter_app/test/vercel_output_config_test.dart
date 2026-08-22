import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../tool/prepare_vercel_output.dart';

void main() {
  test('Vercel output supports SPA routes and microphone access', () {
    final config = buildVercelConfig();
    final routes = config['routes']! as List<Object?>;
    final securityHeaders =
        (routes.first! as Map<String, Object>)['headers']!
            as Map<String, String>;

    expect(config['version'], 3);
    expect(
      routes.whereType<Map<Object?, Object?>>().any(
        (route) => route['handle'] == 'filesystem',
      ),
      isTrue,
    );
    expect((routes.last! as Map<String, Object>)['dest'], '/index.html');
    expect(securityHeaders['X-Frame-Options'], 'DENY');
    expect(
      securityHeaders['Permissions-Policy'],
      contains('microphone=(self)'),
    );
    expect(
      securityHeaders['Content-Security-Policy'],
      contains('wss://*.railway.app'),
    );
  });

  // 這條原本斷言 `_flutter.loader.load();` 一字不差——那是「沒有 serviceWorkerSettings」
  // 的代理指標，但它把「完全不能帶任何參數」也一起釘死了。2026-08-22 加開機遮罩時，
  // `onEntrypointLoaded` 必須是 loader 參數（那是唯一拿得到 appRunner 的地方），
  // 於是這條就擋在路上，卻與它真正要守的東西無關。改成直接斷言那件事本身。
  test('web bootstrap does not register a service worker', () {
    final bootstrap = File('web/flutter_bootstrap.js').readAsStringSync();

    expect(bootstrap, contains('_flutter.loader.load('));
    // 比對「當成 key 傳出去」而不是「字串有出現」——檔頭的註解本來就在解釋為什麼
    // 刻意不帶它，斷言不該把那段說明也一起判成違規。
    expect(bootstrap, isNot(contains(RegExp(r'serviceWorkerSettings\s*:'))));
    expect(bootstrap, isNot(contains('flutter_service_worker.js')));
  });

  // 開機遮罩是 index.html 裡的靜態 DOM，只有 flutter_bootstrap.js 會把它拿掉——
  // 兩邊任一半掉了都不會有錯誤訊息，症狀分別是「永遠白畫面」與「遮罩蓋住可用的
  // App」。CSP 是 `script-src 'self'`（沒有 'unsafe-inline'），所以移除邏輯不能
  // 搬回 index.html 的 inline script，否則本機會動、生產會被擋掉。
  test('boot overlay exists in index.html and is dismissed by the bootstrap', () {
    final html = File('web/index.html').readAsStringSync();
    final bootstrap = File('web/flutter_bootstrap.js').readAsStringSync();

    expect(html, contains('id="boot"'), reason: 'index.html 少了開機遮罩');
    expect(
      html,
      isNot(contains(RegExp(r'<script(?![^>]*\ssrc=)'))),
      reason: "CSP 是 script-src 'self'，index.html 不得有 inline script",
    );
    expect(
      bootstrap,
      contains('onEntrypointLoaded'),
      reason: '沒有這個 callback 就拿不到 appRunner，遮罩會在第一幀之前就消失',
    );
    expect(
      bootstrap,
      contains("getElementById('boot')"),
      reason: '遮罩沒人拿得掉＝蓋在可用的 App 上',
    );
    expect(
      bootstrap,
      contains('setTimeout(_dismissBootOverlay'),
      reason: 'bundle 載入失敗時 callback 不會跑，需要保底的移除',
    );
  });
}
