// 路由守衛的純函式版本：go_router 的 redirect 只負責 lng 前綴與 booted 判斷，
// 「登入 / 角色」規則全部集中在這裡，測試才能不啟動整個 App 就驗到。
//
// 平台史（兩次拍板，方向相反，都要記得）：
//   2026-08-20：Web＝病患語音問診 kiosk；原生 iOS＝醫師專用（不做語音）。
//   2026-08-22：**推翻**。產品改為 iOS 單一 App——候診區 kiosk iPad 跑病患語音問診，
//               醫師/管理員用自己的裝置跑同一顆 App，網頁版走向除役。
// 所以「iOS 專用的平台閘門」整段拆除：問診/病患端路由在 iOS 上重新開放，
// patient-unsupported 提示頁隨之刪除。角色守衛（病患進不了醫師/admin 區）**照舊**，
// 而且在拆閘門前先修掉 `/patients` 前綴誤中的越權洞——拆掉閘門後它是唯一防線。
//
// 平台仍然影響一件事：**醫師 landing**。醫師在手機上打開 App 是要看「有沒有新報告/警示」，
// 所以原生平台落在 /notifications；web（過渡期仍在）維持 /dashboard 不變。

import 'package:flutter/foundation.dart';

/// 原生行動平台（iOS/Android app，非瀏覽器）。
///
/// 2026-08-22 之後它只決定兩件事：醫師 landing（原生→通知頁）與推播註冊
/// （FCM 只在原生上有意義）。它**不再**關閉任何路由——那是被推翻的 2026-08-20 分工。
///
/// 用 `!kIsWeb` 而不是只看 `defaultTargetPlatform`：Flutter Web 跑在 iPad/iPhone Safari 上時
/// `defaultTargetPlatform` 同樣回 `TargetPlatform.iOS`。
/// 測試覆寫方式：`debugDefaultTargetPlatformOverride = TargetPlatform.iOS`（`flutter test`
/// 跑在 VM 上，`kIsWeb` 恆為 false）。純函式 [resolveGuardRedirect] 另外收 bool 參數。
bool get isNativeMobile =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.iOS ||
        defaultTargetPlatform == TargetPlatform.android);

/// 問診相關路由＝病患首頁子樹 + 語音問診子樹。
///
/// 一律用「整段比對」而不是 `startsWith('/patient')`：
///   - `/patient-unsupported` 若被算進來，病患會被 redirect 回自己這一頁 → go_router 迴圈
///   - `/patients`、`/patients/:id` 是醫師端的病患清單，在醫師 App 上必須開著
bool isConsultationArea(String rest) =>
    rest == '/patient' ||
    rest.startsWith('/patient/') ||
    rest == '/conversation' ||
    rest.startsWith('/conversation/');

/// 病患帳號可以待的區域：自己的首頁子樹與問診子樹。
///
/// 一律整段比對。`startsWith('/patient')` 會把醫師端的 `/patients`（病患**清單**）
/// 一起放進來——那正是 2026-08-22 修掉的越權洞。
bool _isPatientOwnArea(String rest) =>
    rest == '/patient' ||
    rest.startsWith('/patient/') ||
    rest == '/conversation' ||
    rest.startsWith('/conversation/');

/// 登入後該落在哪一頁。
///
/// 病患一律回病患首頁（kiosk iPad 上的下一位病患從這裡開始）。
/// 醫師在原生 App 以「通知」為首頁——打開 App 是要看有沒有新報告/警示，
/// 不是看 dashboard 統計；web（過渡期）維持 /dashboard。
String landingPath({
  required String lng,
  required bool isPatient,
  required bool nativeMobile,
}) {
  if (isPatient) return '/$lng/patient';
  return nativeMobile ? '/$lng/notifications' : '/$lng/dashboard';
}

/// booted 之後的 redirect 決策。回傳 null＝放行。
///
/// [path] 是含 lng 前綴的完整路徑，[rest] 是去掉 lng 前綴後的路徑。
String? resolveGuardRedirect({
  required String path,
  required String lng,
  required String rest,
  required bool isAuthenticated,
  required bool isPatient,
  required bool isAdmin,
  required bool nativeMobile,
}) {
  final landing = landingPath(lng: lng, isPatient: isPatient, nativeMobile: nativeMobile);
  // `/register` 必須在公開清單裡：登入頁上就有「建立新帳號」按鈕，漏掉它的結果是
  // 按了被彈回登入頁、看起來像壞掉（React 端本來就公開，2026-08-22 對齊）。
  final isPublic = rest == '/login' ||
      rest == '/register' ||
      rest.startsWith('/forgot-password') ||
      rest.startsWith('/reset-password');

  if (!isAuthenticated) return isPublic ? null : '/$lng/login';
  if (rest == '/login') return landing;
  // Route off the generic role home onto the role-specific landing.
  if (path == '/$lng' || path == '/$lng/') return landing;

  // 舊書籤/推播裡可能還存著已刪除的 iOS 提示頁路徑；當作不存在，交回角色 landing。
  if (rest == '/patient-unsupported') return landing;

  // ---- RoleGuard：病患只能待在病患/問診區；admin 頁需 admin ----
  //
  // ⚠️ 2026-08-22 修正：這裡原本是 `rest.startsWith('/patient')`，而醫師端的病患清單
  // 路由是 `/patients`——**開頭就是 `/patient`**，於是病患帳號可以直接走進
  // `/patients` 與 `/patients/:id`，讀到全院病患的姓名與病歷（實測放行）。
  // 這個洞在 iOS 上一直被平台閘門蓋住（病患整個被擋在提示頁），web 上則是真的開著；
  // 平台閘門拆掉（iOS 開放語音問診）之後它就是唯一的防線，所以改成**整段比對**——
  // 與上方 `isConsultationArea` 的註解警告的是同一個坑，只是當初這一行漏了。
  final isPatientArea = _isPatientOwnArea(rest);
  final isAdminArea = rest == '/admin' || rest.startsWith('/admin/');
  if (isPatient && !isPatientArea) return landing; // patient blocked from doctor/admin
  if (isAdminArea && !isAdmin) return landing; // admin-only subtree
  return null;
}
